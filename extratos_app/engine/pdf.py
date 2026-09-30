"""Extração de texto de PDF preservando as colunas (pdfplumber layout=True)."""
from __future__ import annotations

import io
import logging
import warnings


def linhas_pdf(dados: bytes) -> list[str]:
    import pdfplumber

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    linhas: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pdfplumber.open(io.BytesIO(dados)) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text(layout=True) or ""
                linhas.extend(l.rstrip() for l in texto.splitlines())
    return linhas
