"""Extratos em PDF do Efí Bank (antiga Gerencianet, banco 364).

Dois modelos:

* **Extrato financeiro (Pix/conta):** ``Data Descrição Protocolo Valor``, valor com sinal e
  "Saldo do dia" antes dos lançamentos do dia; lido direto pelo motor de texto.
* **Extrato Financeiro (cobranças):** ``TIPO DE REGISTRO PROTOCOLO DATA VALOR``, com a data
  depois do protocolo, descrição quebrada em até três linhas e "Saldo Diário". As linhas são
  reescritas no formato "data primeiro" antes de ir ao motor.
"""
from __future__ import annotations

import re

from extratos_app.detection.sniffer import FileSample
from extratos_app.engine.texto import PerfilTexto
from extratos_app.parsers.base import registrar
from extratos_app.parsers.texto_base import LayoutPdf

_RODAPE = (r"^EF[IÍ] S\.A\.", r"^OUVIDORIA", r"^EXTRATO FINANCEIRO - P[AÁ]GINA", r"^P[AÁ]GINA \d+ DE \d+")
_REGISTRO = re.compile(r"^(?P<desc>.*?)\s*(?P<protocolo>\d{6,})\s+(?P<data>\d{2}/\d{2}/\d{4})\s+(?P<valor>-?[\d.]+,\d{2})$")
_SALDO = re.compile(r"^(?P<rotulo>Saldo Di[aá]rio)\s+(?P<data>\d{2}/\d{2}/\d{4})\s+(?P<valor>-?[\d.]+,\d{2})$")
_CABECALHO = re.compile(r"^TIPO DE REGISTRO\s+PROTOCOLO\s+DATA\s+VALOR", re.IGNORECASE)


def normalizar_extrato_financeiro(linhas: list[str]) -> list[str]:
    """Reescreve o Extrato Financeiro como "DD/MM/AAAA descrição protocolo valor".

    A descrição de um registro começa numa linha com "•" (tipo • detalhe); o protocolo, a data
    e o valor podem vir na mesma linha ou na seguinte, e o fim do nome, numa linha depois.
    Só o que vem depois do primeiro cabeçalho da tabela é lido.
    """
    saida: list[str] = []
    registros: list[dict[str, str]] = []
    pendente = ""
    na_tabela = False
    for bruta in linhas:
        linha = " ".join(bruta.split())
        if not linha:
            continue
        if _CABECALHO.match(linha):
            na_tabela, pendente = True, ""
            continue
        if not na_tabela or any(re.match(p, linha, re.IGNORECASE) for p in _RODAPE):
            continue
        saldo = _SALDO.match(linha)
        if saldo:
            registros.append({"saldo": f"{saldo['data']} {saldo['rotulo']} {saldo['valor']}"})
            pendente = ""
            continue
        registro = _REGISTRO.match(linha)
        if registro:
            descricao = " ".join(parte for parte in (pendente, registro["desc"]) if parte)
            registros.append({k: registro[k] for k in ("protocolo", "data", "valor")} | {"desc": descricao})
            pendente = ""
        elif "•" in linha:
            pendente = linha  # início de um registro cujo protocolo vem na linha seguinte
        elif pendente:
            pendente = f"{pendente} {linha}"
        elif registros and "desc" in registros[-1]:
            registros[-1]["desc"] = f"{registros[-1]['desc']} {linha}"  # fim do nome do registro
    for registro in registros:
        if "saldo" in registro:
            saida.append(registro["saldo"])
        else:
            saida.append(f"{registro['data']} {registro['desc']} {registro['protocolo']} {registro['valor']}")
    return saida


@registrar
class EfiPdfExtrato(LayoutPdf):
    """Efí 'Extrato financeiro' (Pix e conta): data, descrição, protocolo e valor com sinal."""

    id, nome, banco = "efi_pdf_extrato", "Efí (Gerencianet) – PDF (extrato de conta)", "Efí"
    obrigatorias = (r"\bEFI S\.A\.", r"DATA DESCRICAO PROTOCOLO VALOR")
    perfil = PerfilTexto(
        ignorar=(r"^EF[IÍ] S\.A\.", r"^OUVIDORIA", r"^LAN[CÇ]AMENTOS$", r"^DATA DESCRI[CÇ][AÃ]O PROTOCOLO",
                 r"^FILTROS APLICADOS", r"^PER[IÍ]ODO TIPO DE SALDO", r"^\d{2}/\d{2}/\d{4} - \d{2}/\d{2}/\d{4}"),
        complemento="anterior",
    )


@registrar
class EfiPdfFinanceiro(LayoutPdf):
    """Efí 'Extrato Financeiro' de cobranças: protocolo antes da data (linhas reordenadas)."""

    id, nome, banco = "efi_pdf_financeiro", "Efí (Gerencianet) – PDF (extrato financeiro de cobranças)", "Efí"
    obrigatorias = (r"\bEFI S\.A\.", r"TIPO DE REGISTRO PROTOCOLO DATA VALOR")
    perfil = PerfilTexto(complemento="nenhum")

    def linhas(self, amostra: FileSample) -> list[str]:
        return normalizar_extrato_financeiro(super().linhas(amostra))
