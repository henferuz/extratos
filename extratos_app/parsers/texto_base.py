"""Base dos layouts lidos pelo motor de texto (relatórios TXT e PDFs)."""
from __future__ import annotations

import re

from extratos_app.detection.sniffer import PDF, TEXTO, FileSample
from extratos_app.engine.pdf import linhas_pdf
from extratos_app.engine.texto import MotorTexto, PerfilTexto
from extratos_app.models import ResultadoImportacao
from extratos_app.parsers.base import LayoutPorAssinatura


class LayoutTexto(LayoutPorAssinatura):
    perfil: PerfilTexto = PerfilTexto()
    banco: str = ""

    def linhas(self, amostra: FileSample) -> list[str]:
        if amostra.tipo == PDF:
            return linhas_pdf(amostra.bytes)
        return amostra.texto.splitlines()

    def parsear(self, amostra: FileSample) -> ResultadoImportacao:
        res = ResultadoImportacao(arquivo=amostra.caminho.name, layout_id=self.id, layout_nome=self.nome, banco=self.banco)
        linhas = self.linhas(amostra)
        if amostra.tipo == PDF and not any(l.strip() for l in linhas):
            res.avisos.append("PDF sem texto (digitalizado): não é possível extrair lançamentos.")
            return res
        MotorTexto(self.perfil).processar(linhas, res)
        m = re.search(r"CONTA(?:\s+CORRENTE)?\s*[:.]*\s*([\dXx][\dXx.\-/ ]{3,15}[\dXx])", amostra.texto_normalizado)
        if m:
            res.conta = m.group(1).strip()
        return res


class LayoutTxt(LayoutTexto):
    tipos = frozenset({TEXTO})


class LayoutPdf(LayoutTexto):
    tipos = frozenset({PDF})
