"""Itaú — extratos em PDF (14 amostras, ~10 variações de cabeçalho).

Sinal: '-' antes ou depois do valor (inclusive separado: '146,88 -'); valor sem sinal = crédito.
Linhas 'SALDO APLIC AUT MAIS' / 'SDO CTA/APL AUTOMATICAS' são saldos de aplicação, não da conta.
"""
from __future__ import annotations

from extratos_app.engine.texto import SALDO_FORA_DA_CONTA, PerfilTexto
from extratos_app.parsers.base import registrar
from extratos_app.parsers.texto_base import LayoutPdf

# cabeçalhos das variações encontradas nas amostras
_CABECALHOS_ITAU = (
    r"ITAU ?EMPRESAS|LOGOTIPO ITAU|BANCO ITAU"
    r"|LANCAMENTOS DO PERIODO: \d"
    r"|PERIODO DE VISUALIZACAO"
    r"|EXTRATO CONTA CORRENTE / LANCAMENTOS"
    r"|EXTRATO - POR PERIODO"
    r"|HISTORICO DE LANCAMENTOS ORIG"
    r"|RESULTADO DE TODAS AS TRANSACOES DE"
    r"|AG\./ORIGEM VALOR \(R\$\) SALDO \(R\$\)"
)


@registrar
class ItauPdf(LayoutPdf):
    id, nome, banco = "itau_pdf", "Itaú – PDF", "Itaú"
    obrigatorias = (_CABECALHOS_ITAU, r"SALDO (ANTERIOR|INICIAL|TOTAL DISPONIVEL|EM CONTA)|SALDO RESUMIDO")
    opcionais = (r"SISPAG", r"APLIC AUT MAIS", r"REND PAGO", r"AG\.? ?/ ?ORIGEM")
    proibidas = (r"EXTRATO MENSAL.*MINHA CONTA",)
    perfil = PerfilTexto(
        inicio=r"^(DATA|DATA\s+LANCAMENTO|DATA LANCAMENTO)\b|LANCAMENTOS?\s+(DETALHES|CNPJ|RAZAO|VALOR)|^DATA\s",
        fim=(
            r"^POSICAO DA CONTA CORRENTE$|^AVISO:|^OS SALDOS ACIMA|^TOTAL PARA SAQUE"
            r"|^LIMITE DA CONTA E SALDO|^\(\+\) SDO|^DESCRICAO VALOR \(R\$\)"
            r"|^LANCAMENTOS FUTUROS|^SAIDAS FUTURAS|^POSICAO CONSOLIDADA"
        ),
        ignorar=(r"^AG\.?$", r"^ORIGEM$", r"^LOGOTIPO", r"^ATUALIZACAO:", r"^\d{2}/\d{2}/\d{4}, \d{2}:\d{2}"),
        saldo_fora_da_conta=SALDO_FORA_DA_CONTA + r"|SDO CTA/APL",
    )


@registrar
class ItauPdfConsolidado(LayoutPdf):
    """'Extrato mensal' consolidado: colunas entradas (créditos) / saídas (débitos) / saldo."""

    id, nome, banco = "itau_pdf_consolidado", "Itaú – PDF (extrato mensal consolidado)", "Itaú"
    obrigatorias = (r"EXTRATO MENSAL", r"MINHA CONTA", r"CONTA CORRENTE ?\| ?MOVIMENTACAO")
    perfil = PerfilTexto(
        inicio=r"CONTA CORRENTE ?\| ?MOVIMENTACAO",
        fim=r"CONTA CORRENTE ?\| ?LIMITE|APLICACOES AUTOMATICAS ?\||^\d{2}\. |^TOTALIZADOR DE APLICACOES",
        ignorar=(r"^[A-Z] ?= ?[A-Z]+$", r"^PARA DEMAIS SIGLAS", r"^EXPLICATIVAS", r"^\(CREDITOS\)", r"^\(DEBITOS\)"),
        limpar_descricao=r"^([A-Z] ?= ?[a-zà-ú ]+|pela ?Bolsa de Valores|Para demais siglas, consulte as Notas|Explicativas no ?final do ?extrato)\s*",
        # 'Saldo anterior'/'Saldo final' somam conta + aplicação; o saldo da linha é só da conta
        saldo_fora_da_conta=SALDO_FORA_DA_CONTA + r"|SDO CTA/APL|SALDO ANTERIOR|SALDO FINAL",
    )
