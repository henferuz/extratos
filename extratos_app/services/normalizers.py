"""Conversões de texto para número/data no padrão brasileiro."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_ESPACOS = re.compile(r"\s+")
_FORMATOS_DATA = (
    "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d.%m.%y",
    "%Y/%m/%d", "%d-%m-%y", "%Y%m%d", "%d%m%Y",
)
MESES = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
    "feb": 2, "apr": 4, "may": 5, "aug": 8, "sep": 9, "oct": 10, "dec": 12,
}


def sem_acentos(texto: str) -> str:
    """Remove acentos e também ícones de fonte (caracteres de uso privado, comuns em PDFs de internet banking)."""
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) not in ("Mn", "Co"))


def limpar_texto(valor: object) -> str:
    if valor is None:
        return ""
    return _ESPACOS.sub(" ", str(valor)).strip()


def parse_valor(valor: object) -> Decimal | None:
    """Converte '1.500,00', '-1.500,00', '1.500,00 D', '(1.500,00)', 'R$ 1,5', '1500.00', 1500.0 em Decimal com sinal.

    'D', '-' ou parênteses => negativo; 'C' ou '+' => positivo. Prefixos US$, $ e R$ são removidos.
    Com ',' e '.', o último separador é decimal e o outro é milhar. Só ',' aceita um separador;
    vários pontos são milhar, e um único ponto com três casas é milhar se a parte inteira
    tiver 1–3 dígitos e for diferente de zero; nos demais casos, o ponto é decimal.
    Retorna None se não for valor.
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor)).quantize(Decimal("0.01")) if valor == valor else None
    texto = limpar_texto(valor).upper().replace("US$", "").replace("R$", "").replace("$", "").replace(" ", "")
    if not texto:
        return None
    negativo = False
    if texto.startswith("(") and texto.endswith(")"):
        negativo, texto = True, texto[1:-1]
    if texto[-1:] in ("D", "C") and len(texto) > 1:
        negativo = negativo or texto[-1] == "D"
        texto = texto[:-1]
    if texto[-1:] in ("-", "+"):
        negativo = negativo or texto[-1] == "-"
        texto = texto[:-1]
    if texto[:1] in ("-", "+"):
        negativo = negativo or texto[0] == "-"
        texto = texto[1:]
    if not re.fullmatch(r"\d[\d.,]*", texto):
        return None
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        if texto.count(",") != 1:
            return None
        texto = texto.replace(",", ".")
    elif texto.count(".") > 1 or (
        match := re.fullmatch(r"(\d{1,3})\.(\d{3})", texto)
    ) and int(match.group(1)) != 0:
        texto = texto.replace(".", "")
    try:
        numero = Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -numero if negativo else numero


def parse_data(valor: object) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = limpar_texto(valor)
    if not texto:
        return None
    texto = texto.split(" ")[0].split("T")[0]
    for formato in _FORMATOS_DATA:
        try:
            d = datetime.strptime(texto, formato).date()
        except ValueError:
            continue
        if 1990 <= d.year <= 2100:
            return d
    return None


def formatar_moeda(valor: Decimal) -> str:
    """Decimal -> 'R$ 1.500,00'."""
    texto = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if valor < 0 else ''}R$ {texto}"
