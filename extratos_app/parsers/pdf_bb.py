"""Banco do Brasil — extratos em PDF.

As amostras são anonimizadas (sem o nome do banco); a detecção usa a estrutura do cabeçalho
de cada modelo. O "extrato de empréstimos" (modelo 5 das amostras) não é conta corrente e
fica de fora de propósito.
"""
from __future__ import annotations

from extratos_app.engine.texto import PerfilTexto
from extratos_app.parsers.base import registrar
from extratos_app.parsers.texto_base import LayoutPdf

_NAO_CONTA_CORRENTE = (r"EXTRATO DE EMPRESTIMOS", r"OPERACAO DE CREDITO", r"CLIENTE OU FORNECEDOR")


@registrar
class BancoBrasilPdfBalancete(LayoutPdf):
    """'Dt. balancete / Dt. movimento / Ag. origem / Lote / Histórico / Documento' com sufixo C/D."""

    id, nome, banco = "bb_pdf_balancete", "Banco do Brasil – PDF (Dt. balancete)", "Banco do Brasil"
    obrigatorias = (r"DT\. BALANCETE", r"DT\. MOVIMENTO", r"HISTORICO", r"\d,\d{2} [CD]\b")
    proibidas = _NAO_CONTA_CORRENTE
    perfil = PerfilTexto(
        inicio=r"DT\. BALANCETE",
        fim=r"^INFORMACOES ADICIONAIS|^TOTAL APLICACOES",
        ignorar=(r"BLOQUEAD|BLOQ\.", r"^LANCAMENTOS$"),
    )


@registrar
class BancoBrasilPdfSinais(LayoutPdf):
    """'Extrato de Conta Corrente / Lançamentos / Dia ... Histórico ... Valor' com (+)/(-).

    Nas variações com Lote/Documento o histórico fica acima da linha do valor e o complemento
    abaixo — resolvido pela atribuição por proximidade do motor.
    """

    id, nome, banco = "bb_pdf_sinais", "Banco do Brasil – PDF (valores com (+)/(-))", "Banco do Brasil"
    obrigatorias = (r"EXTRATO DE CONTA CORRENTE", r"LANCAMENTOS DIA", r"\d,\d{2} \([+-]\)")
    opcionais = (r"DIA LOTE DOCUMENTO HISTORICO VALOR", r"DIA HISTORICO VALOR", r"SALDO ANTERIOR")
    proibidas = _NAO_CONTA_CORRENTE
    perfil = PerfilTexto(
        inicio=r"^DIA\b.*\bVALOR",
        fim=r"^TOTAL APLICACOES|^\* SALDOS POR DIA|^INFORMACOES ADICIONAIS|^OBSERVACOES",
        ignorar=(r"BLOQUEAD|BLOQ\.",),
    )


@registrar
class BancoBrasilPdfDataDia(LayoutPdf):
    """'Data / Dia / Histórico / Lote / Banco Origem / Documento / Valor - R$ / Saldo - R$' (dd.mm.aaaa, C/D)."""

    id, nome, banco = "bb_pdf_data_dia", "Banco do Brasil – PDF (Extrato de Conta)", "Banco do Brasil"
    obrigatorias = (r"DATA DIA HISTORICO LOTE", r"VALOR - R\$", r"\d,\d{2} [CD]\b")
    opcionais = (r"SISBB", r"BB RESPONDE", r"SALDO ANTERIOR")
    proibidas = _NAO_CONTA_CORRENTE
    perfil = PerfilTexto(
        inicio=r"DATA DIA\s+HISTORICO|DATA DIA HISTORICO",
        fim=r"^INFORMACOES ADICIONAIS|^TOTAL APLICACOES|^OBSERVACOES",
        ignorar=(r"BLOQUEAD|BLOQ\.", r"^MOD\. \d", r"SISBB"),
    )
