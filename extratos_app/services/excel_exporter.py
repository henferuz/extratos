"""Exportação determinística de :class:`ResultadoImportacao` para XLSX."""
from __future__ import annotations

import re
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from extratos_app.models import ENTRADA, ResultadoImportacao
from extratos_app.services.normalizers import parse_data, parse_valor

_FORMATO_MOEDA = '"R$" #,##0.00'
_FORMATO_DATA = "dd/mm/yyyy"
_CINZA_CABECALHO = "00D9D9D9"
_VERDE_ENTRADA = "00E2EFDA"
_VERDE_FONTE = "00375623"
_VERMELHO_SAIDA = "00FCE4E4"
_VERMELHO_FONTE = "009C0006"
_CINZA_BORDA = "00BFBFBF"
_BORDA_LINHA = Side(style="thin", color=_CINZA_BORDA)
_BORDA = Border(left=_BORDA_LINHA, right=_BORDA_LINHA, top=_BORDA_LINHA, bottom=_BORDA_LINHA)
_FONTE_NEGRITO = Font(bold=True)
_FONTE_ENTRADA = Font(color=_VERDE_FONTE)
_FONTE_SAIDA = Font(color=_VERMELHO_FONTE)
_FONTE_TOTAL_ENTRADA = Font(bold=True, color=_VERDE_FONTE)
_FONTE_TOTAL_SAIDA = Font(bold=True, color=_VERMELHO_FONTE)
_PREENCHIMENTO_CABECALHO = PatternFill("solid", fgColor=_CINZA_CABECALHO)
_PREENCHIMENTO_ENTRADA = PatternFill("solid", fgColor=_VERDE_ENTRADA)
_PREENCHIMENTO_SAIDA = PatternFill("solid", fgColor=_VERMELHO_SAIDA)
_ALINHAMENTO_ESQUERDA = Alignment(horizontal="left", vertical="center")
_ALINHAMENTO_CENTRO = Alignment(horizontal="center", vertical="center")
_ALINHAMENTO_DIREITA = Alignment(horizontal="right", vertical="center")
_ALINHAMENTO_DIREITA_SIMPLES = Alignment(horizontal="right")
_ALINHAMENTO_CABECALHO = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _gravar_texto(cell, valor: object) -> None:
    if valor in (None, ""):
        cell.value = None
        return
    texto = str(valor)
    cell.value = texto
    cell.data_type = "s"
    cell.quotePrefix = texto[:1] in "=+-@"


def _moeda(valor: Decimal | int | float | None) -> float | None:
    if valor is None:
        return None
    return float(Decimal(str(valor)).quantize(Decimal("0.01")))


def _estilizar_cabecalho(ws) -> None:
    for coluna in range(1, ws.max_column + 1):
        cell = ws.cell(1, coluna)
        cell.font = _FONTE_NEGRITO
        cell.fill = _PREENCHIMENTO_CABECALHO
        cell.alignment = _ALINHAMENTO_CABECALHO
        cell.border = _BORDA


def _estilizar_tabela(ws, ultima_linha: int, ultima_coluna: int) -> None:
    for row in ws.iter_rows(min_row=2, max_row=ultima_linha, min_col=1, max_col=ultima_coluna):
        for cell in row:
            cell.border = _BORDA


def _ordenar_movimentos(res: ResultadoImportacao):
    return sorted(
        enumerate(res.movimentos),
        key=lambda par: (
            par[1].data or datetime.max.date(),
            par[1].linha_origem if par[1].linha_origem is not None else par[0],
            par[0],
        ),
    )


def _formatar_data(data) -> datetime | None:
    if data is None:
        return None
    return datetime.combine(data, time.min)


class ExcelExporter:
    def exportar(self, res: ResultadoImportacao, destino: Path | str) -> Path:
        destino = Path(destino)
        if destino.suffix.lower() != ".xlsx":
            raise ValueError("O arquivo deve ter extensão .xlsx")
        if not res.movimentos:
            raise ValueError("Não há lançamentos para exportar")

        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(".tmp.xlsx")
        try:
            temporario.unlink(missing_ok=True)
            wb = Workbook()
            ws = wb.active
            ws.title = "Movimentos"
            self._movimentos(ws, res)
            self._resumo(wb.create_sheet("Resumo"), res, ws.max_row - 2, ws)
            if res.erros or res.avisos or res.trechos_falhos:
                self._ocorrencias(wb.create_sheet("Ocorrências"), res)
            wb.save(temporario)
            wb.close()
            temporario.replace(destino)
            return destino
        except Exception:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _movimentos(self, ws, res: ResultadoImportacao) -> None:
        extras: list[str] = []
        for movimento in res.movimentos:
            for chave in movimento.extras:
                if chave != "Complemento" and chave not in extras:
                    extras.append(chave)
        cabecalho = ["Data", "Documento", "Descrição", "Complemento", "Entrada", "Saída", *extras]
        ws.append(cabecalho)
        _estilizar_cabecalho(ws)
        larguras = [len(str(valor or "")) for valor in cabecalho]
        linha = 1

        for _, movimento in _ordenar_movimentos(res):
            valores = [
                _formatar_data(movimento.data),
                str(movimento.documento) if movimento.documento not in (None, "") else None,
                movimento.descricao,
                movimento.extras.get("Complemento"),
                _moeda(movimento.valor) if movimento.tipo == ENTRADA else None,
                _moeda(movimento.valor) if movimento.tipo != ENTRADA else None,
                *[self._extra_valor(movimento.extras.get(chave), chave) for chave in extras],
            ]
            ws.append(valores)
            linha += 1
            for indice, valor in enumerate(valores):
                larguras[indice] = max(larguras[indice], len(str(valor or "")))
            for coluna in (3, 4):
                _gravar_texto(ws.cell(linha, coluna), ws.cell(linha, coluna).value)
            for coluna in range(7, len(cabecalho) + 1):
                cell = ws.cell(linha, coluna)
                if isinstance(cell.value, str):
                    _gravar_texto(cell, cell.value)
            for coluna, valor in enumerate(valores, start=1):
                cell = ws.cell(linha, coluna)
                cell.alignment = _ALINHAMENTO_ESQUERDA
                if coluna == 1:
                    cell.alignment = _ALINHAMENTO_CENTRO
                    cell.number_format = _FORMATO_DATA
                elif coluna == 2:
                    cell.number_format = "@"
                elif coluna in (5, 6):
                    cell.alignment = _ALINHAMENTO_DIREITA
                    cell.number_format = _FORMATO_MOEDA
                elif cabecalho[coluna - 1] in ("Bruto", "Líquido"):
                    cell.alignment = _ALINHAMENTO_DIREITA
                    cell.number_format = _FORMATO_MOEDA
                elif cabecalho[coluna - 1] == "Data pagamento" and valor:
                    cell.number_format = _FORMATO_DATA
            if movimento.tipo == ENTRADA:
                ws.cell(linha, 5).fill = _PREENCHIMENTO_ENTRADA
                ws.cell(linha, 5).font = _FONTE_ENTRADA
            else:
                ws.cell(linha, 6).fill = _PREENCHIMENTO_SAIDA
                ws.cell(linha, 6).font = _FONTE_SAIDA

        ultima_linha = linha
        ultima_coluna = len(cabecalho)
        _estilizar_tabela(ws, ultima_linha, ultima_coluna)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(ultima_coluna)}{ultima_linha}"

        total = ultima_linha + 2
        ws.cell(total, 1, "Totais")
        ws.cell(total, 1).font = _FONTE_NEGRITO
        ws.cell(total, 5, f"=SUBTOTAL(9,E2:E{ultima_linha})")
        ws.cell(total, 6, f"=SUBTOTAL(9,F2:F{ultima_linha})")
        for coluna in (5, 6):
            cell = ws.cell(total, coluna)
            cell.number_format = _FORMATO_MOEDA
            cell.alignment = _ALINHAMENTO_DIREITA_SIMPLES
            cell.fill = _PREENCHIMENTO_ENTRADA if coluna == 5 else _PREENCHIMENTO_SAIDA
            cell.font = _FONTE_TOTAL_ENTRADA if coluna == 5 else _FONTE_TOTAL_SAIDA
        for coluna in range(1, ultima_coluna + 1):
            ws.cell(total, coluna).border = _BORDA

        for coluna in range(1, ultima_coluna + 1):
            letra = get_column_letter(coluna)
            if coluna == 1:
                ws.column_dimensions[letra].width = 12
            elif coluna in (5, 6):
                ws.column_dimensions[letra].width = 16
            else:
                ws.column_dimensions[letra].width = min(60, max(10, larguras[coluna - 1] + 2))

    @staticmethod
    def _extra_valor(valor, chave: str):
        if valor in (None, ""):
            return None
        if chave in ("Bruto", "Líquido"):
            numero = parse_valor(valor)
            return _moeda(numero) if numero is not None else None
        if chave == "Data pagamento":
            data = parse_data(valor)
            return _formatar_data(data) if data else str(valor)
        return str(valor)

    def _resumo(self, ws, res: ResultadoImportacao, ultima_linha_movimentos: int, movimentos_ws) -> None:
        periodo = res.periodo
        periodo_texto = "—" if periodo is None else f"{periodo[0]:%d/%m/%Y} a {periodo[1]:%d/%m/%Y}"
        linhas = [
            ("Arquivo", res.arquivo),
            ("Tipo identificado", res.layout_nome or res.layout_id or "—"),
            ("Banco", res.banco or "—"),
            ("Conta", res.conta or "—"),
            ("Período", periodo_texto),
            ("Registros encontrados", len(res.movimentos)),
            ("Entradas (qtd)", len(res.entradas)),
            ("Saídas (qtd)", len(res.saidas)),
            ("Total de entradas", f"=SUM(Movimentos!E2:E{ultima_linha_movimentos})"),
            ("Total de saídas", f"=SUM(Movimentos!F2:F{ultima_linha_movimentos})"),
            ("Diferença", "=B9-B10"),
            ("Saldo inicial", _moeda(res.saldo_inicial) if res.saldo_inicial is not None else "—"),
            ("Saldo final", _moeda(res.saldo_final) if res.saldo_final is not None else "—"),
            ("Conferência de saldos", res.conferencia or "—"),
            ("Registros ignorados", res.ignorados),
            ("Registros com erro", len(res.erros)),
            ("Gerado em", datetime.now()),
        ]
        cabecalhos = {
            str(movimentos_ws.cell(1, coluna).value): coluna
            for coluna in range(1, movimentos_ws.max_column + 1)
        }
        if "Bruto" in cabecalhos or "Líquido" in cabecalhos:
            if "Bruto" in cabecalhos:
                coluna = get_column_letter(cabecalhos["Bruto"])
                linhas.insert(11, ("Total bruto", f"=SUM(Movimentos!{coluna}2:{coluna}{ultima_linha_movimentos})"))
            linhas.insert(12, ("Total de taxas", f'=SUMIF(Movimentos!C2:C{ultima_linha_movimentos},"Taxa -*",Movimentos!F2:F{ultima_linha_movimentos})'))
            if "Líquido" in cabecalhos:
                coluna = get_column_letter(cabecalhos["Líquido"])
                linhas.insert(13, ("Total líquido", f"=SUM(Movimentos!{coluna}2:{coluna}{ultima_linha_movimentos})"))
        for linha, (rotulo, valor) in enumerate(linhas, start=1):
            ws.cell(linha, 1, rotulo)
            ws.cell(linha, 2, valor)
            if isinstance(valor, str) and rotulo not in {
                "Total de entradas", "Total de saídas", "Diferença", "Total bruto", "Total de taxas", "Total líquido"
            }:
                _gravar_texto(ws.cell(linha, 2), valor)
            ws.cell(linha, 1).font = _FONTE_NEGRITO
            ws.cell(linha, 1).border = _BORDA
            ws.cell(linha, 2).border = _BORDA
            if rotulo in {"Total de entradas", "Total de saídas", "Diferença", "Saldo inicial", "Saldo final"}:
                ws.cell(linha, 2).number_format = _FORMATO_MOEDA
            if rotulo == "Gerado em":
                ws.cell(linha, 2).number_format = "dd/mm/yyyy hh:mm"
        ws.column_dimensions["A"].width = 28
        ws.column_dimensions["B"].width = 55

    def _ocorrencias(self, ws, res: ResultadoImportacao) -> None:
        ws.append(["Tipo", "Linha do arquivo", "Motivo", "Conteúdo"])
        _estilizar_cabecalho(ws)
        for erro in res.erros:
            ws.append(["Erro", erro.linha, erro.motivo, erro.conteudo])
        for aviso in res.avisos:
            ws.append(["Aviso", None, aviso, None])
        familias = sorted(res.trechos_falhos, key=lambda chave: (chave != "conta", chave))
        for familia in familias:
            for inicio, fim in res.trechos_falhos[familia]:
                ws.append([
                    "Conferência",
                    f"{inicio}–{fim}",
                    f"Saldos entre as linhas {inicio} e {fim} não conferem com os lançamentos",
                    familia,
                ])
        for linha in range(2, ws.max_row + 1):
            cell = ws.cell(linha, 4)
            if isinstance(cell.value, str):
                _gravar_texto(cell, cell.value)
        ws.append([f"Linhas ignoradas de propósito (saldos, bloqueios): {res.ignorados}"])
        _estilizar_tabela(ws, ws.max_row, 4)
        ws.column_dimensions["A"].width = 18
        ws.column_dimensions["B"].width = 18
        ws.column_dimensions["C"].width = 72
        ws.column_dimensions["D"].width = 60


def nome_sugerido(res: ResultadoImportacao) -> str:
    base = re.sub(r"\.[^.\\/]+$", "", str(res.arquivo))
    base = re.sub(r'[\\/:*?"<>|]', "_", base)
    sufixo = "_convertido"
    if res.periodo:
        inicio, fim = res.periodo
        sufixo += f"_{inicio:%Y-%m}"
        if (inicio.year, inicio.month) != (fim.year, fim.month):
            sufixo += f"_a_{fim:%Y-%m}"
    return f"{base}{sufixo}.xlsx"
