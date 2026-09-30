"""Leitura única e barata do arquivo para os detectores de layout.

Os detectores olham só para o `FileSample`: tipo real (pelos bytes, não pela extensão),
texto inicial, texto das primeiras páginas do PDF e primeiras linhas das planilhas.
"""
from __future__ import annotations

import csv
import io
import logging
import warnings
import zipfile
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from extratos_app.services.normalizers import limpar_texto, sem_acentos

PDF, XLSX, XLS, CSV, OFX, TEXTO, DESCONHECIDO = "pdf", "xlsx", "xls", "csv", "ofx", "texto", "desconhecido"
LINHAS_PLANILHA = 60


def decodificar(dados: bytes) -> str:
    codificacoes = ["utf-8-sig"]
    tem_bom_utf16 = dados.startswith((b"\xff\xfe", b"\xfe\xff"))
    muitos_nulos = dados[:4000].count(b"\x00") > max(4, min(len(dados[:4000]) // 10, 100))
    if tem_bom_utf16 or muitos_nulos:
        codificacoes.append("utf-16")
    codificacoes.append("cp1252")
    for enc in codificacoes:
        try:
            return dados.decode(enc)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1", errors="replace")


def _tipo_real(caminho: Path, cabeca: bytes) -> str:
    ext = caminho.suffix.lower()
    if cabeca.startswith(b"%PDF"):
        return PDF
    if cabeca.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(cabeca)) as arquivo:
                tipos = arquivo.read("[Content_Types].xml").lower()
            if b"spreadsheetml" in tipos or b"excel" in tipos:
                return XLSX
            return DESCONHECIDO
        except (KeyError, zipfile.BadZipFile):
            return DESCONHECIDO
    if cabeca.startswith(b"\xd0\xcf\x11\xe0"):
        return XLS
    amostra = decodificar(cabeca[:4000]).upper()
    if "OFXHEADER" in amostra or "<OFX>" in amostra:
        return OFX
    if ext == ".csv":
        return CSV
    if ext in (".xlsx", ".xls", ".pdf", ".ofx"):
        return DESCONHECIDO  # extensão diz uma coisa, conteúdo outra
    if b"\x00" in cabeca[:4000]:
        return DESCONHECIDO
    # texto com separador consistente é tratado como CSV
    linhas = [l for l in amostra.splitlines()[:10] if l.strip()]
    if len(linhas) >= 2:
        for sep in (";", "\t"):
            contagens = {l.count(sep) for l in linhas}
            if len(contagens) == 1 and min(contagens) >= 2:
                return CSV
    return TEXTO


@dataclass
class FileSample:
    caminho: Path
    tipo: str
    tamanho: int
    _bytes: bytes = field(repr=False, default=b"")
    protegido_por_senha: bool = False

    @classmethod
    def ler(cls, caminho: Path | str) -> "FileSample":
        caminho = Path(caminho)
        dados = caminho.read_bytes()
        return cls(caminho=caminho, tipo=_tipo_real(caminho, dados), tamanho=len(dados), _bytes=dados)

    @property
    def bytes(self) -> bytes:
        return self._bytes

    @cached_property
    def texto(self) -> str:
        """Texto integral (TXT/CSV/OFX) ou das duas primeiras páginas (PDF)."""
        if self.tipo in (TEXTO, CSV, OFX):
            return decodificar(self._bytes)
        if self.tipo == PDF:
            return self._texto_pdf(paginas=2)
        if self.tipo in (XLSX, XLS):
            return "\n".join(" | ".join(c for c in linha if c) for aba in self.planilhas.values() for linha in aba)
        return ""

    @cached_property
    def texto_normalizado(self) -> str:
        """Maiúsculo, sem acentos e com espaços simples: base para as assinaturas."""
        return limpar_texto(sem_acentos(self.texto).upper())

    @cached_property
    def planilhas(self) -> dict[str, list[list[str]]]:
        """Primeiras linhas de cada aba como texto (XLSX, XLS ou CSV)."""
        try:
            if self.tipo == XLSX:
                return ler_xlsx(self.caminho, LINHAS_PLANILHA)
            if self.tipo == XLS:
                return ler_xls(self.caminho, LINHAS_PLANILHA)
            if self.tipo == CSV:
                return {"csv": ler_csv(self._bytes, LINHAS_PLANILHA)}
        except Exception:  # noqa: BLE001 - arquivo corrompido vira "não reconhecido"
            return {}
        return {}

    def _texto_pdf(self, paginas: int) -> str:
        try:
            import pdfplumber
            from pdfminer.pdfdocument import PDFPasswordIncorrect
            from pdfplumber.utils.exceptions import PdfminerException

            logging.getLogger("pdfminer").setLevel(logging.ERROR)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with pdfplumber.open(io.BytesIO(self._bytes)) as pdf:
                    return "\n".join((p.extract_text() or "") for p in pdf.pages[:paginas])
        except (PDFPasswordIncorrect, PdfminerException) as exc:
            if isinstance(exc, PDFPasswordIncorrect) or (exc.args and isinstance(exc.args[0], PDFPasswordIncorrect)):
                self.protegido_por_senha = True
            return ""
        except Exception:  # noqa: BLE001
            return ""


def _celula(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def ler_xlsx(caminho: Path, limite: int | None = None, valores_brutos: bool = False) -> dict[str, list[list]]:
    """Lê as abas de um XLSX.

    Com ``valores_brutos=False`` as células viram texto: essa visão serve **apenas**
    para assinatura de layout. Os motores extraem valores com ``valores_brutos=True``.
    """
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    abas: dict[str, list[list]] = {}
    try:
        for ws in wb.worksheets:
            linhas = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if limite is not None and i >= limite:
                    break
                linhas.append(list(row) if valores_brutos else [_celula(v) for v in row])
            abas[ws.title] = linhas
    finally:
        wb.close()
    return abas


def ler_xls(caminho: Path, limite: int | None = None, valores_brutos: bool = False) -> dict[str, list[list]]:
    """Lê as abas de um XLS legado.

    Com ``valores_brutos=False`` as células viram texto: essa visão serve **apenas**
    para assinatura de layout. Os motores extraem valores com ``valores_brutos=True``.
    """
    import xlrd

    wb = xlrd.open_workbook(str(caminho))
    abas: dict[str, list[list]] = {}
    for ws in wb.sheets():
        n = ws.nrows if limite is None else min(ws.nrows, limite)
        linhas = []
        for r in range(n):
            row = []
            for c in range(ws.ncols):
                cel = ws.cell(r, c)
                if cel.ctype == xlrd.XL_CELL_DATE:
                    v = xlrd.xldate.xldate_as_datetime(cel.value, wb.datemode)
                else:
                    v = cel.value
                row.append(v if valores_brutos else _celula(v))
            linhas.append(row)
        abas[ws.name] = linhas
    return abas


def ler_csv(dados: bytes, limite: int | None = None) -> list[list[str]]:
    texto = decodificar(dados)
    amostra = texto[:5000]
    sep = max((";", ",", "\t", "|"), key=amostra.count)
    leitor = csv.reader(io.StringIO(texto), delimiter=sep)
    linhas = []
    for i, row in enumerate(leitor):
        if limite is not None and i >= limite:
            break
        linhas.append([c.strip() for c in row])
    return linhas
