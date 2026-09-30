"""Relatórios TXT de bancos (amostras: BB, Bradesco, Sicredi, Banrisul)."""
from __future__ import annotations

from extratos_app.engine.texto import PerfilTexto
from extratos_app.parsers.base import registrar
from extratos_app.parsers.texto_base import LayoutTxt


@registrar
class BancoBrasilTxt(LayoutTxt):
    """'Extrato conta corrente' / SISBB. Valor com sufixo C/D; depósito bloqueado sem sufixo ou com '*'."""

    id, nome, banco = "bb_txt", "Banco do Brasil – TXT", "Banco do Brasil"
    obrigatorias = (r"EXTRATO (DE )?CONTA CORRENTE", r"SALDO ANTERIOR", r"\d,\d{2} [CD]\b")
    opcionais = (r"SISBB", r"DT\. MOVIMENTO", r"LANCAMENTOS", r"HISTORICO")
    perfil = PerfilTexto(
        inicio=r"(DT\. MOVIMENTO|^DATA\s+AG)",
        fim=r"^-{20,}$|OBSERVACOES|TRANSACAO EFETUADA",
        ignorar=(r"BLOQUEAD|BLOQ\.", r"^={5,}", r"^-{5,}"),
        empate="anterior",
    )


@registrar
class BradescoTxt(LayoutTxt):
    """Colunas Crédito/Débito; data só na primeira linha do dia; complemento na linha de baixo."""

    id, nome, banco = "bradesco_txt", "Bradesco – TXT", "Bradesco"
    obrigatorias = (r"CREDITO( \(R\$\))?\s+DEBITO", r"SALDO ANTERIOR")
    opcionais = (r"AGENCIA:\s*\S+\s+CONTA:", r"DCTO\.|DOCTO", r"MOVIMENTACAO DO PERIODO|DEMONSTRATIVO|EXTRATO DE:")
    proibidas = (r"SICREDI|COOP\.?CRED|S A L D O",)
    perfil = PerfilTexto(
        ignorar=(r"^AGENCIA:", r"EXTRATO PARA SIMPLES", r"^(SEGUNDA|TERCA|QUARTA|QUINTA|SEXTA|SABADO|DOMINGO),"),
        empate="anterior",
        complemento="anterior",
    )


@registrar
class SicrediTxt(LayoutTxt):
    """Colunas DEBITO/CREDITO/SALDO; saldo anterior 'S A L D O  A N T E R I O R'."""

    id, nome, banco = "sicredi_txt", "Sicredi – TXT", "Sicredi"
    obrigatorias = (r"EXTRATO DE CONTA CORRENTE", r"DEBITO\s+CREDITO\s+SALDO", r"S A L D O\s+A N T E R I O R")
    opcionais = (r"COOP|C\.C\.P\.I", r"PERIODO: DE", r"SICREDI")
    perfil = PerfilTexto(
        fim=r"^LIMITE\(S\) PRE-APROVADO|GENTE QUE COOPERA|^IOF ADICIONAL|CUSTO EFETIVO",
        ignorar=(r"^={5,}", r"^PAG\.:", r"^PERIODO:", r"^DISP\.:"),
        saldo=r"S A L D O|D E T R A N S P O R T E|^SALDO",
        saldo_inicial=r"S A L D O\s+A N T E R I O R|SALDO ANTERIOR",
        complemento="anterior",
    )


@registrar
class BanrisulTxt(LayoutTxt):
    """Valor com '-' no fim para débito; dia isolado + título '++ MOVIMENTOS MMM/AAAA'."""

    id, nome, banco = "banrisul_txt", "Banrisul – TXT", "Banrisul"
    obrigatorias = (r"B A N R I S U L|BANCO DO ESTADO DO RIO GRANDE DO SUL", r"MOVIMENTOS DA CONTA CORRENTE")
    opcionais = (r"SALDO ANT EM", r"PARA SIMPLES CONFERENCIA")
    perfil = PerfilTexto(
        inicio=r"MOVIMENTOS DA CONTA CORRENTE",
        fim=r"EXTRATO EMITIDO|^-+ ?(RESUMO|APLICAC|LIMITE)|^TOTAL DE (CREDITOS|DEBITOS)",
        mes_titulo=r"MOVIMENTOS\s+([A-Z]{3})/(\d{4})",
        dia_isolado=True,
        ignorar=(r"^-{5,}", r"^CNPJ-CPF", r"^-\+"),
        saldo=r"^(SALDO|TOTAL\b)",
        saldo_inicial=r"SALDO ANT\b",
        limpar_descricao=r"\s[A-Z]{3}$",  # sistema de origem (BRR, BDP, BPX...)
        complemento="anterior",
    )
