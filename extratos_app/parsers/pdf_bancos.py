"""Extratos em PDF de Bradesco, Santander, Caixa, Sicoob, Sicredi, Inter e relatório Omie.

Cada classe é um layout identificado pela estrutura do cabeçalho das amostras reais
(que são anonimizadas). Documentos que não são extrato de conta corrente (aplicações,
CDB, extrato internacional) ficam de fora pelas assinaturas `proibidas`.
"""
from __future__ import annotations

from extratos_app.engine.texto import SALDO_FORA_DA_CONTA, PerfilTexto
from extratos_app.parsers.base import registrar
from extratos_app.parsers.texto_base import LayoutPdf

_RODAPES = (r"^\d{2}/\d{2}/\d{2,4}, \d{2}:\d{2}", r"^HTTPS?://", r"^PAGE \d+ OF \d+", r"^ABOUT:BLANK")


# ----------------------------------------------------------------------------- Bradesco
@registrar
class BradescoPdfMensal(LayoutPdf):
    """'Extrato Mensal / Por Período': colunas Crédito (R$) / Débito (R$) / Saldo (R$)."""

    id, nome, banco = "bradesco_pdf_mensal", "Bradesco – PDF (extrato mensal/por período)", "Bradesco"
    obrigatorias = (r"EXTRATO MENSAL / POR PERIODO", r"CREDITO \(R\$\) DEBITO \(R\$\)")
    perfil = PerfilTexto(
        ignorar=(*_RODAPES, r"^EXTRATO DE:", r"^TOTAL DISPONIVEL", r"^AGENCIA \| CONTA"),
        fim=r"^OS DADOS ACIMA|^ULTIMOS LANCAMENTOS|^SALDOS INVEST|^INVESTIMENTOS",
        empate="proximo",
    )


@registrar
class BradescoPdfNet(LayoutPdf):
    """'Busca de lançamentos': histórico acima, valor com Tipo Crédito/Débito, complemento abaixo."""

    id, nome, banco = "bradesco_pdf_lancamentos", "Bradesco – PDF (busca de lançamentos)", "Bradesco"
    obrigatorias = (r"BUSCA DE LANCAMENTOS", r"DATA DESCRICAO DOCUMENTO TIPO VALOR SALDO")
    perfil = PerfilTexto(
        ignorar=(*_RODAPES, r"^AG\d+.*SEQ\d+$"),
        limpar_descricao=r"(?i)\b(cr[ée]dito|d[ée]bito)\s*$",
        empate="proximo",
    )


# ----------------------------------------------------------------------------- Santander
# Bancos sem leitor próprio cujo PDF tem a mesma estrutura de outro banco: a marca do
# cabeçalho vira layout próprio (mesma leitura) para o Excel mostrar o banco certo.
_FIBRA = r"INTERNET BANKING - BANCO FIBRA"
_BANESE = r"NIB\.BANESE\.COM\.BR|BANESE, PODE CONTAR"
_SAFRA = r"EXTRATO DE MOVIMENTACAO SAFRA"
_NAO_SANTANDER_CC = (r"SICOOB", r"INVESTIMENTOS >", r"PATRIMONIO LIQUIDO", r"CONTAMAX EMPRESARIAL > VER EXTRATO")


@registrar
class SantanderPdf(LayoutPdf):
    """Internet Banking / App Santander: 'Data Histórico [Documento] Valor [Saldo]', sinal '-' ou 'R$'.

    Cobre também as variações com data por extenso ('Quarta, 31 de janeiro de 2024') e com
    colunas Crédito/Débito.
    """

    id, nome, banco = "santander_pdf", "Santander – PDF", "Santander"
    obrigatorias = (
        r"INTERNET BANKING|APLICATIVO SANTANDER|SANTANDER|CONTAMAX|GETNET",
        r"DATA HISTORICO|DATA DESCRICAO DOCTO|CONTA CORRENTE > EXTRATO|\d{1,2} DE [A-Z]+ DE \d{4} [A-Z]",
    )
    opcionais = (r"CONTAMAX", r"GETNET", r"SALDO DO DIA", r"PERIODOS?:")
    proibidas = (*_NAO_SANTANDER_CC, r"PERIODO(?: DE)? 7 DIAS", _FIBRA)
    perfil = PerfilTexto(
        ignorar=(
            *_RODAPES, r"^INTERNET BANKING", r"^AGENCIA", r"^CONTA CORRENTE >", r"^PERIODOS?:", r"^DATA/HORA",
            r"^OPCAO DE PESQUISA", r"^SALDO DISPONIVEL PARA USO", r"^ULTIMO ACESSO", r"^TROCAR CONTA",
        ),
        fim=r"^SALDOS? POR PERIODO|^LIMITE CHEQUE|^PROVISAO DE ENCARGOS|^TOTAL DE (CREDITOS|DEBITOS)|^SALDO DE CONTAMAX|^SALDO ANTERIOR$|^SALDO DE CONTA CORRENTE$",
        limpar_descricao=r"\s(CREDITO|DEBITO)$",
    )


@registrar
class FibraPdf(SantanderPdf):
    """Internet Banking Banco Fibra: mesma estrutura do PDF do Santander."""

    id, nome, banco = "fibra_pdf", "Banco Fibra – PDF", "Banco Fibra"
    obrigatorias = (_FIBRA, SantanderPdf.obrigatorias[1])
    proibidas = tuple(p for p in SantanderPdf.proibidas if p != _FIBRA)


@registrar
class SantanderPdfInterno(LayoutPdf):
    """'Extrato de conta para simples conferência - uso interno' (Dt. Contábil / Histórico)."""

    id, nome, banco = "santander_pdf_interno", "Santander – PDF (conferência interna)", "Santander"
    obrigatorias = (r"EXTRATO DE CONTA PARA SIMPLES CONFERENCIA", r"DT\. CONTABIL HISTORICO")
    perfil = PerfilTexto(ignorar=_RODAPES, fim=r"^TOTAL(IZADOR)? ", empate="anterior")


# ----------------------------------------------------------------------------- Caixa
_CEF_CABECALHOS = (
    r"SIHEX|CAIXA ECONOMICA|GERE\.?NCIADOR CAIXA|SAC CAIXA|NR\. ?DOC|DATA MOV\.|DATA MOVTO|SALDO ANTERIOR AO PERIODO SOLICITADO"
    r"|DATA DE LANCAMENTO|DATA DE DATA DE DOCUMENTO HISTORICO|EXTRATO HISTORICO DA CONTA"
)


@registrar
class CaixaPdf(LayoutPdf):
    """Caixa: valores com C/D (colados ou não), 'SALDO DIA', saldo às vezes em linha própria."""

    id, nome, banco = "cef_pdf", "Caixa Econômica Federal – PDF", "Caixa Econômica Federal"
    obrigatorias = (_CEF_CABECALHOS, r"HISTORICO", r"SALDO")
    opcionais = (r"SALDO DIA", r"EXTRATO POR PERIODO", r"GERE\.?NCIADOR CAIXA")
    # SIHEX: duas colunas de lançamentos por página; CDB: informativo de aplicação
    proibidas = (r"UNICRED", r"SIHEX", r"INFORMATIVO MENSAL CDB", r"EXTRATO PIX", r"\d{6}\.\d{2} \d{6}\.\d{2}", r"SALDO ANTERIOR AO PERIODO SOLICITADO", _BANESE, _SAFRA)
    perfil = PerfilTexto(
        ignorar=(*_RODAPES, r"^INFORMACOES DO LIMITE", r"^\* \d+ - ", r"^\d{2}/\d{2} \d{2}:\d{2}$"),
        fim=r"^INFORMACOES DO LIMITE|^SAC CAIXA|^LANCAMENTOS FUTUROS|^JUROS PROV",
        saldo=r"^(SALDO|S A L D O|TOTAL\b)",
        empate="anterior",
    )


@registrar
class BanesePdf(CaixaPdf):
    """Banese (netbanking): mesma estrutura do extrato da Caixa."""

    id, nome, banco = "banese_pdf", "Banese – PDF", "Banese"
    obrigatorias = (_BANESE, *CaixaPdf.obrigatorias)
    proibidas = tuple(p for p in CaixaPdf.proibidas if p != _BANESE)


@registrar
class SafraPdf(CaixaPdf):
    """Safra 'Extrato de movimentação': mesma estrutura do extrato da Caixa."""

    id, nome, banco = "safra_pdf", "Safra – PDF", "Safra"
    obrigatorias = (_SAFRA, *CaixaPdf.obrigatorias)
    proibidas = tuple(p for p in CaixaPdf.proibidas if p != _SAFRA)


@registrar
class CaixaPdfPeriodoSolicitado(LayoutPdf):
    """Caixa 'Saldo anterior ao período solicitado': valor '- R$ 915,79' e saldo 'R$ 29.608,62 C'
    (só o saldo leva C/D); células quebradas em várias linhas."""

    id, nome, banco = "cef_pdf_periodo", "Caixa Econômica Federal – PDF (período solicitado)", "Caixa Econômica Federal"
    obrigatorias = (r"SALDO ANTERIOR AO PERIODO SOLICITADO", r"DATA DOCUMENTO HISTORICO VALOR SALDO")
    perfil = PerfilTexto(
        ignorar=(*_RODAPES, r"^\d{2}/\d{2} \d{2}:\d{2}"),
        fim=r"^SAC CAIXA|^LANCAMENTOS FUTUROS",
        saldo_se_sufixo_cd=True,
        saldo_inicial=r"SALDO ANTERIOR",
    )


@registrar
class CaixaPdfPonto(LayoutPdf):
    """Caixa 'Extrato por período via internet' com valores em formato 1234.56 (ponto decimal)."""

    id, nome, banco = "cef_pdf_ponto", "Caixa Econômica Federal – PDF (valores com ponto)", "Caixa Econômica Federal"
    obrigatorias = (r"EXTRATO POR PERIODO", r"DATA DE DATA DE", r"\d+\.\d{2} \d+\.\d{2}")
    perfil = PerfilTexto(decimal_ponto=True, ignorar=_RODAPES, fim=r"^SAC CAIXA|^LANCAMENTOS FUTUROS")


@registrar
class CaixaPdfPix(LayoutPdf):
    """Caixa 'Extrato Pix': tipo ENVIADO/RECEBIDO (ou PAGAMENTO/RECEBIMENTO) define o sentido."""

    id, nome, banco = "cef_pdf_pix", "Caixa Econômica Federal – PDF (extrato Pix)", "Caixa Econômica Federal"
    obrigatorias = (r"EXTRATO PIX", r"DATA HORA (TIPO DE PIX|TRANSACAO)")
    perfil = PerfilTexto(
        ignorar=_RODAPES,
        debito_se=r"\b(ENVIADO|PAGAMENTO)\b",
        credito_se=r"\b(RECEBIDO|RECEBIMENTO)\b",
        empate="proximo",
    )


# ----------------------------------------------------------------------------- Sicoob
@registrar
class SicoobPdf(LayoutPdf):
    """Sicoob/Sisbr 'Extrato (de) conta corrente': valor com C/D colado, '*' = bloqueado."""

    id, nome, banco = "sicoob_pdf", "Sicoob – PDF", "Sicoob"
    obrigatorias = (r"SICOOB|SISBR", r"EXTRATO (DE )?CONTA CORRENTE")
    opcionais = (r"SALDO ANTERIOR", r"SALDO DO DIA", r"COOP(ERATIVA)?\.?:")
    proibidas = (r"APROPRIACAO DIARIA", r"CLIENTE OU FORNECEDOR")
    perfil = PerfilTexto(
        ignorar=(*_RODAPES, r"^SICOOB", r"^SISBR", r"^COOP", r"^CONTA:", r"^PERIODO", r"^DOC\.:\s*$"),
        fim=r"^RESUMO$|^SALDO EM C/C|^\(\+\) SALDO|^SALDO BLOQUEADO$|^OUVIDORIA SICOOB|^LIMITE (DE )?CHEQUE",
        saldo_fora_da_conta=SALDO_FORA_DA_CONTA,
        complemento="anterior",
    )


@registrar
class SicoobPdfDetalhado(LayoutPdf):
    """'Extrato detalhado conta / Últimos lançamentos': valor com '-' e saldo na linha."""

    id, nome, banco = "sicoob_pdf_detalhado", "Sicoob – PDF (extrato detalhado)", "Sicoob"
    obrigatorias = (r"EXTRATO DETALHADO CONTA", r"ULTIMOS LANCAMENTOS", r"DATA HISTORICO DOCUMENTO VALOR SALDO")
    perfil = PerfilTexto(ignorar=_RODAPES, saldo_inicial=r"SALDO ANTERIOR")


# ----------------------------------------------------------------------------- Sicredi
@registrar
class SicrediPdf(LayoutPdf):
    """Sicredi: 'Data Descrição Documento Valor Saldo' (sinal '-') ou '+ R$ / - R$'; poupança sem sinal."""

    id, nome, banco = "sicredi_pdf", "Sicredi – PDF", "Sicredi"
    obrigatorias = (
        r"SICREDI.*COOPERATIVA:|COOPERATIVA:.*SICREDI|ASSOCIADO: .*COOPERATIVA:|PIX_CRED|MOMENTO DE EMISSAO",
        r"SALDO ANTERIOR|MOVIMENTACOES DE",
    )
    opcionais = (r"PIX_CRED|PIX_DEB", r"COOPERATIVA")
    proibidas = (r"SICOOB",)
    perfil = PerfilTexto(
        ignorar=(*_RODAPES, r"^\(R\$\)$", r"^SICREDI", r"^ASSOCIADO", r"^COOPERATIVA", r"^IMPRESSO EM"),
        fim=r"^LANCAMENTOS FUTUROS|^SALDO DA CONTA CAPITAL|^LIMITE|^INFORMACOES COMPLEMENTARES|^OUVIDORIA",
        complemento="anterior",
    )


# ----------------------------------------------------------------------------- Inter
@registrar
class InterPdf(LayoutPdf):
    """Banco Inter: '-R$' para saídas; data em linha própria por extenso ('27 de Fevereiro de 2023')."""

    id, nome, banco = "inter_pdf", "Banco Inter – PDF", "Banco Inter"
    obrigatorias = (r"BANCO INTER|EXTRATO CONTA CORRENTE PJ|INSTITUICAO: ,", r"SALDO")
    opcionais = (r"SOLICITADO EM", r"PERIODO:")
    perfil = PerfilTexto(
        ignorar=(*_RODAPES, r"^SAC\b", r"^OUVIDORIA", r"^DEFICIENTE", r"^FALE COM A GENTE", r"^\d+ DE \d+$"),
        fim=r"^INFORMACOES ADICIONAIS|^FALE COM A GENTE",
        # "Saldo do dia" vem no topo do dia mas é o saldo depois dos lançamentos; cada linha já traz o saldo
        ignorar_valor=(r"SALDO DO DIA:",),
        complemento="anterior",
    )


# ----------------------------------------------------------------------------- Omie
@registrar
class OmieExtratoPdf(LayoutPdf):
    """Relatório de extrato gerado pelo ERP Omie (conta de qualquer banco): valor com '-' e saldo."""

    id, nome, banco = "omie_pdf", "Omie – relatório de extrato (PDF)", ""
    obrigatorias = (r"SITUACAO DATA CLIENTE OU FORNECEDOR DOCUMENTO CATEGORIA VALOR SALDO",)
    perfil = PerfilTexto(
        antes_da_data=r"(?i)^\s*(conciliado|pendente|previsto|atrasado|n[ãa]o conciliado)\s",
        ignorar=_RODAPES,
        complemento="nenhum",
    )
