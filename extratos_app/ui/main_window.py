"""Janela Tkinter e fluxo assíncrono do conversor."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import END, DISABLED, NORMAL, StringVar, Text, Tk, filedialog, messagebox, ttk

from extratos_app.detection.sniffer import FileSample
from extratos_app.models import ResultadoImportacao
from extratos_app.services.excel_exporter import ExcelExporter, nome_sugerido
from extratos_app.services.importer import importar
from extratos_app.ui.apresentacao import mensagem_erro, mensagens_importacao, resumo_para_exibicao

_FILTROS = [
    ("Arquivos suportados", "*.pdf *.ofx *.txt *.csv *.xlsx *.xls"),
    ("PDF", "*.pdf"),
    ("OFX", "*.ofx"),
    ("Texto", "*.txt"),
    ("Planilhas", "*.xlsx *.xls *.csv"),
    ("Todos", "*.*"),
]
_LOGGERS: dict[Path, logging.Logger] = {}


def contar_linhas_planilha(amostra: FileSample) -> int | None:
    """Conta linhas sem materializar a tabela inteira na thread da interface."""
    if amostra.tipo == "csv":
        return amostra.bytes.count(b"\n") + (1 if amostra.bytes and not amostra.bytes.endswith(b"\n") else 0)
    if amostra.tipo == "xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(amostra.caminho, read_only=True, data_only=True)
        try:
            return sum(ws.max_row or 0 for ws in wb.worksheets)
        finally:
            wb.close()
    if amostra.tipo == "xls":
        import xlrd

        wb = xlrd.open_workbook(str(amostra.caminho), on_demand=True)
        try:
            return sum(ws.nrows for ws in wb.sheets())
        finally:
            wb.release_resources()
    return None


def registrar_aviso_planilha_grande(logger: logging.Logger, amostra: FileSample) -> int | None:
    """Registra o limite operacional de 100 mil linhas e retorna a contagem."""
    try:
        linhas = contar_linhas_planilha(amostra)
    except Exception:  # noqa: BLE001 - a importação ainda tentará produzir diagnóstico próprio
        return None
    if linhas is not None and linhas > 100_000:
        logger.warning("planilha grande: %s linhas; a importação pode demorar", linhas)
    return linhas


def configurar_logger() -> logging.Logger:
    pasta = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "ConversorExtratos"
    caminho = pasta / "extratos.log"
    if caminho in _LOGGERS:
        return _LOGGERS[caminho]
    logger = logging.getLogger(f"conversor_extratos.{caminho}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(caminho, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    except OSError:
        handler = logging.NullHandler()
    logger.addHandler(handler)
    _LOGGERS[caminho] = logger
    return logger


class JanelaPrincipal(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Conversor de Extratos")
        self.minsize(820, 600)
        self._logger = configurar_logger()
        self._fila: queue.Queue[tuple[str, object]] = queue.Queue()
        self._fila_exportacao: queue.Queue[tuple[str, object]] = queue.Queue()
        self._processando = False
        self._exportando = False
        self.resultado: ResultadoImportacao | None = None
        self.caminho: Path | None = None
        self._montar_estilo()
        self._montar_widgets()

    def _montar_estilo(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("vista")
        except tk_tcl_error():
            try:
                self.style.theme_use("clam")
            except tk_tcl_error():
                pass

    def _montar_widgets(self) -> None:
        botoes = ttk.Frame(self, padding=10)
        botoes.pack(fill="x")
        self.btn_importar = ttk.Button(botoes, text="Importar arquivo", command=self._escolher_arquivo)
        self.btn_importar.pack(side="left")
        self.btn_exportar = ttk.Button(botoes, text="Gerar Excel", command=self._escolher_destino, state=DISABLED)
        self.btn_exportar.pack(side="left", padx=(8, 0))
        self.status_var = StringVar(value="Selecione um extrato para começar.")
        ttk.Label(botoes, text="Status").pack(side="left", padx=(16, 0))
        self.status = ttk.Label(botoes, textvariable=self.status_var)
        self.status.pack(side="left", padx=16)
        self.progress = ttk.Progressbar(botoes, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        self.progress.pack_forget()

        arquivo = ttk.LabelFrame(self, text="Arquivo", padding=8)
        arquivo.pack(fill="x", padx=10, pady=(0, 8))
        self.arquivo_var = StringVar(value="—")
        self.tipo_var = StringVar(value="—")
        self.periodo_var = StringVar(value="—")
        for linha, (rotulo, variavel) in enumerate((("Arquivo selecionado", self.arquivo_var), ("Tipo identificado", self.tipo_var), ("Período", self.periodo_var))):
            ttk.Label(arquivo, text=f"{rotulo}:").grid(row=linha, column=0, sticky="w", padx=(0, 8))
            ttk.Label(arquivo, textvariable=variavel).grid(row=linha, column=1, sticky="w")

        resumo = ttk.LabelFrame(self, text="Resumo", padding=8)
        resumo.pack(fill="x", padx=10, pady=(0, 8))
        self._resumo_frame = resumo
        self._resumo_labels: dict[str, tuple[ttk.Label, ttk.Label]] = {}
        self._limpar_resumo()

        self.aviso_var = StringVar(value="")
        self.aviso = ttk.Label(self, textvariable=self.aviso_var, padding=8)
        self.aviso.pack(fill="x", padx=10)

        preview = ttk.LabelFrame(self, text="Pré-visualização (até 200 lançamentos)", padding=8)
        preview.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.tree = ttk.Treeview(preview, columns=("Data", "Descrição", "Entrada", "Saída"), show="headings", height=8)
        for coluna in ("Data", "Descrição", "Entrada", "Saída"):
            self.tree.heading(coluna, text=coluna)
        self.tree.column("Data", width=100, anchor="center")
        self.tree.column("Descrição", width=420, anchor="w")
        self.tree.column("Entrada", width=120, anchor="e")
        self.tree.column("Saída", width=120, anchor="e")
        self.tree.tag_configure("entrada", background="#E2EFDA")
        self.tree.tag_configure("saida", background="#FCE4E4")
        self.tree.pack(fill="both", expand=True)
        self.preview_footer = ttk.Label(preview, text="")
        self.preview_footer.pack(anchor="w")

        log_frame = ttk.LabelFrame(self, text="Log", padding=8)
        log_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.log_text = Text(log_frame, height=8, state=DISABLED, wrap="word")
        for nivel, cor in (("normal", "#333333"), ("aviso", "#EF6C00"), ("erro", "#C62828"), ("ok", "#2E7D32")):
            self.log_text.tag_configure(nivel, foreground=cor)
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _limpar_resumo(self) -> None:
        for child in self._resumo_frame.winfo_children():
            child.destroy()
        self._resumo_labels.clear()
        for linha, rotulo in enumerate(("Arquivo", "Tipo identificado", "Período", "Registros encontrados", "Entradas", "Saídas", "Total de entradas", "Total de saídas", "Diferença", "Saldo inicial", "Saldo final", "Conferência")):
            label = ttk.Label(self._resumo_frame, text=rotulo)
            valor = ttk.Label(self._resumo_frame, text="—")
            label.grid(row=linha // 2, column=(linha % 2) * 2, sticky="w", padx=(0, 6), pady=2)
            valor.grid(row=linha // 2, column=(linha % 2) * 2 + 1, sticky="w", padx=(0, 20), pady=2)
            self._resumo_labels[rotulo] = (label, valor)

    def _escolher_arquivo(self) -> None:
        caminho = filedialog.askopenfilename(filetypes=_FILTROS)
        if caminho:
            self._iniciar_importacao(Path(caminho))

    def _iniciar_importacao(self, caminho: Path | str) -> None:
        if self._processando:
            return
        caminho = Path(caminho)
        try:
            if caminho.stat().st_size > 50 * 1024 * 1024 and not messagebox.askyesno("Arquivo grande", "O arquivo tem mais de 50 MB. Deseja continuar?"):
                return
        except OSError:
            pass
        self._processando = True
        self.caminho = caminho
        self.arquivo_var.set(caminho.name)
        self.resultado = None
        self.btn_importar.configure(state=DISABLED)
        self.btn_exportar.configure(state=DISABLED)
        self.progress.pack(side="right")
        self.progress.start(12)
        self.status_var.set("⏳ Processando...")
        self.status.configure(foreground="")
        threading.Thread(target=self._trabalhar_importacao, args=(self.caminho,), daemon=True).start()
        self.after(100, self._verificar_fila)

    def _trabalhar_importacao(self, caminho: Path) -> None:
        inicio = time.perf_counter()
        tipo = "erro"
        valor: object = RuntimeError("A importação foi interrompida sem resultado.")
        try:
            amostra = FileSample.ler(caminho)
            self._logger.info("início arquivo=%s tamanho=%s tipo=%s", caminho, amostra.tamanho, amostra.tipo)
            registrar_aviso_planilha_grande(self._logger, amostra)
            valor = importar(caminho, amostra)
            self._logger.info("layout=%s tempo_parsing=%.3fs", valor.layout_id, time.perf_counter() - inicio)
            tipo = "ok"
        except BaseException as exc:  # noqa: BLE001 - garante resultado mesmo em interrupção
            valor = exc
            self._logger.exception("falha arquivo=%s", caminho)
        finally:
            self._fila.put((tipo, valor))

    def report_callback_exception(self, exc: type[BaseException], valor: BaseException, tb) -> None:
        self._logger.error("erro inesperado na interface", exc_info=(exc, valor, tb))
        self._processando = False
        if not self._exportando:
            self.progress.stop()
            self.progress.pack_forget()
        self.btn_importar.configure(state=DISABLED if self._exportando else NORMAL)
        self.btn_exportar.configure(state=NORMAL if self.resultado and not self._exportando else DISABLED)
        messagebox.showerror("Erro inesperado", "Erro inesperado. Consulte o log para mais detalhes.")

    def _verificar_fila(self) -> None:
        try:
            tipo, valor = self._fila.get_nowait()
        except queue.Empty:
            if self._processando:
                self.after(100, self._verificar_fila)
            return
        self._processando = False
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_importar.configure(state=NORMAL)
        if tipo == "ok":
            self._aplicar_resultado(valor)  # type: ignore[arg-type]
        else:
            self._aplicar_erro(valor)  # type: ignore[arg-type]

    def _aplicar_resultado(self, resultado: ResultadoImportacao) -> None:
        self.resultado = resultado
        self.status_var.set("✔ Arquivo reconhecido com sucesso")
        self.status.configure(foreground="#2E7D32")
        self.arquivo_var.set(resultado.arquivo)
        self.tipo_var.set(resultado.layout_nome or resultado.layout_id or "—")
        periodo = resultado.periodo
        self.periodo_var.set("—" if not periodo else f"{periodo[0]:%d/%m/%Y} a {periodo[1]:%d/%m/%Y}")
        for rotulo, valor, estilo in resumo_para_exibicao(resultado):
            if rotulo in self._resumo_labels:
                cor = {"entrada": "#2E7D32", "saida": "#C62828", "ok": "#2E7D32", "alerta": "#EF6C00"}.get(estilo, "")
                self._resumo_labels[rotulo][1].configure(text=valor, foreground=cor)
        self._mostrar_aviso(resultado)
        self._mostrar_preview(resultado)
        for nivel, texto in mensagens_importacao(resultado):
            self._log(nivel, texto)
        self.btn_exportar.configure(state=NORMAL)

    def _aplicar_erro(self, exc: Exception) -> None:
        self.resultado = None
        self.status_var.set("✖ " + mensagem_erro(exc))
        self.status.configure(foreground="#C62828")
        self.tipo_var.set("Não identificado")
        self.periodo_var.set("—")
        self._limpar_resumo()
        self._mostrar_preview(None)
        self._mostrar_aviso(None)
        self._log("erro", mensagem_erro(exc))
        self.btn_exportar.configure(state=DISABLED)

    def _mostrar_aviso(self, resultado: ResultadoImportacao | None) -> None:
        if resultado is None or resultado.conferencia == "ok":
            self.aviso_var.set("")
        elif resultado.conferencia.startswith("divergente"):
            self.aviso_var.set("Atenção: os saldos do arquivo não fecham com os lançamentos lidos. Confira a aba Ocorrências do Excel.")
        elif resultado.conferencia == "sem líquido para conferir":
            self.aviso_var.set("O arquivo não traz valor líquido para conferência automática.")
        else:
            self.aviso_var.set("O arquivo não traz saldos para conferência automática.")

    def _mostrar_preview(self, resultado: ResultadoImportacao | None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        if resultado is None:
            self.preview_footer.configure(text="")
            return
        limite = resultado.movimentos[:200]
        for movimento in limite:
            entrada = formatar(movimento.valor) if movimento.tipo == "ENTRADA" else ""
            saida = formatar(movimento.valor) if movimento.tipo == "SAIDA" else ""
            self.tree.insert("", "end", values=(movimento.data.strftime("%d/%m/%Y"), movimento.descricao, entrada, saida), tags=("entrada" if movimento.tipo == "ENTRADA" else "saida",))
        self.preview_footer.configure(text=f"Mostrando {len(limite)} de {len(resultado.movimentos)}" if len(resultado.movimentos) > 200 else "")

    def _escolher_destino(self) -> None:
        if not self.resultado or self._processando or self._exportando:
            return
        initialdir = str(self.caminho.parent) if self.caminho else None
        destino = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")], initialfile=nome_sugerido(self.resultado), initialdir=initialdir
        )
        if destino:
            self._exportar(Path(destino))

    def _exportar(self, destino: Path | str) -> None:
        if not self.resultado or self._processando or self._exportando:
            return
        self._exportando = True
        self.btn_importar.configure(state=DISABLED)
        self.btn_exportar.configure(state=DISABLED)
        self.progress.pack(side="right")
        self.progress.start(12)
        threading.Thread(
            target=self._trabalhar_exportacao,
            args=(self.resultado, destino),
            daemon=True,
        ).start()
        self.after(100, self._verificar_exportacao)

    def _trabalhar_exportacao(self, resultado: ResultadoImportacao, destino: Path | str) -> None:
        try:
            caminho = ExcelExporter().exportar(resultado, destino)
            self._fila_exportacao.put(("ok", caminho))
        except Exception as exc:  # noqa: BLE001 - mensagem amigável na interface
            self._logger.exception("falha ao gerar excel")
            self._fila_exportacao.put(("erro", exc))

    def _verificar_exportacao(self) -> None:
        try:
            tipo, valor = self._fila_exportacao.get_nowait()
        except queue.Empty:
            if self._exportando:
                self.after(100, self._verificar_exportacao)
            return

        self._exportando = False
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_importar.configure(state=NORMAL)
        self.btn_exportar.configure(state=NORMAL if self.resultado else DISABLED)
        if tipo == "ok":
            caminho = Path(valor)
            self._logger.info("excel gerado=%s", caminho)
            self._log("ok", f"Excel gerado com sucesso: {caminho}.")
            if messagebox.askyesno("Concluído", "Arquivo Excel gerado com sucesso.\n\nDeseja abrir a pasta?"):
                os.startfile(str(caminho.parent))
        else:
            exc = valor
            messagebox.showerror("Erro", mensagem_erro(exc))  # type: ignore[arg-type]
            self._log("erro", mensagem_erro(exc))  # type: ignore[arg-type]

    def _log(self, nivel: str, texto: str) -> None:
        self.log_text.configure(state=NORMAL)
        self.log_text.insert(END, f"{time.strftime('%H:%M:%S')} {texto}\n", (nivel,))
        self.log_text.see(END)
        self.log_text.configure(state=DISABLED)


def formatar(valor) -> str:
    from extratos_app.services.normalizers import formatar_moeda

    return formatar_moeda(valor)


def tk_tcl_error():
    import tkinter

    return tkinter.TclError
