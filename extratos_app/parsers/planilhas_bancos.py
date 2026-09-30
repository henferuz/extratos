"""Extratos bancários em planilha (XLSX/XLS/CSV).

Todos usam o motor genérico de planilhas; cada classe só identifica o banco/modelo pela
assinatura do conteúdo (texto das primeiras linhas), para o usuário ver qual layout foi
reconhecido. O último layout é o genérico: qualquer planilha com tabela Data + Valor.
"""
from __future__ import annotations

from extratos_app.detection.sniffer import FileSample
from extratos_app.engine.planilha import PerfilPlanilha
from extratos_app.parsers.base import registrar
from extratos_app.parsers.planilha_base import LayoutPlanilha

_NAO_EXTRATO = (r"CUSTODIA", r"\bUSD\b", r"CARTEIRA \| DETALHES \| ISIN")


@registrar
class ItauPlanilha(LayoutPlanilha):
    id, nome, banco = "itau_xlsx", "Itaú – planilha", "Itaú"
    obrigatorias = (r"DATA \| LANCAMENTO|TEFS RECEBIDAS", r"VALOR")
    opcionais = (r"LOGOTIPO ITAU|AGENCIA/CONTA", r"SALDO ANTERIOR", r"ATUALIZACAO:")
    proibidas = (*_NAO_EXTRATO, r"BRADESCO|SAFRA|SANTANDER|PAGSEGURO|BANESTES|COOPERATIVA|UNICRED")


@registrar
class BradescoPlanilha(LayoutPlanilha):
    id, nome, banco = "bradesco_xlsx", "Bradesco – planilha", "Bradesco"
    obrigatorias = (r"BRADESCO NET EMPRESA|EXTRATO UNIFICADO - PESSOA JURIDICA|INVEST FACIL BRADESCO",)
    perfil = PerfilPlanilha(saldo_fora_da_conta=r"INVEST|APLIC|TOTAL DISPONIVEL")


@registrar
class SantanderPlanilha(LayoutPlanilha):
    id, nome, banco = "santander_xlsx", "Santander – planilha", "Santander"
    obrigatorias = (r"SANTANDER|DATA \| HISTORICO \| DOCUMENTO \| VALOR", r"HISTORICO")
    proibidas = (*_NAO_EXTRATO, r"BRADESCO|SAFRA|SICOOB|BANESTES|PAGSEGURO")


@registrar
class SafraPlanilha(LayoutPlanilha):
    id, nome, banco = "safra_xlsx", "Safra – planilha", "Safra"
    obrigatorias = (r"BANCO SAFRA",)
    perfil = PerfilPlanilha(ignorar=r"^QUANT\. EVENTOS")


@registrar
class SicoobPlanilha(LayoutPlanilha):
    id, nome, banco = "sicoob_xlsx", "Sicoob – planilha", "Sicoob"
    obrigatorias = (r"EXTRATO CONTA CORRENTE", r"DATA \| DOCUMENTO \| HISTORICO \| VALOR")


@registrar
class UnicredPlanilha(LayoutPlanilha):
    id, nome, banco = "unicred_xlsx", "Unicred – planilha", "Unicred"
    obrigatorias = (r"EXTRATO DE CONTA CORRENTE PARA SIMPLES CONFERENCIA", r"COOPERATIVA")


@registrar
class PagBankPlanilha(LayoutPlanilha):
    id, nome, banco = "pagbank_xlsx", "PagBank – planilha", "PagBank"
    obrigatorias = (r"PAGSEGURO|PAGBANK", r"ENTRADAS \| SAIDAS")


@registrar
class StoneContaPlanilha(LayoutPlanilha):
    """Stone Conta: 'Movimentação | Tipo | Valor | Saldo antes | Saldo depois | Tarifa | Data'."""

    id, nome, banco = "stone_conta_xlsx", "Stone Conta Digital – planilha", "Stone"
    obrigatorias = (r"MOVIMENTACAO \| TIPO \| VALOR \| SALDO ANTES \| SALDO DEPOIS",)
    perfil = PerfilPlanilha(
        colunas={
            **PerfilPlanilha().colunas,
            "tipo": r"^MOVIMENTACAO$",
            "descricao": r"^TIPO$",
            "complemento": r"^DESTINO$",
            "documento": r"^NOSSO NUMERO$",
        }
    )


@registrar
class StoneExtratoPlanilha(LayoutPlanilha):
    """Stone 'Extrato de conta corrente' convertido em Excel (uma aba por página)."""

    id, nome, banco = "stone_extrato_xlsx", "Stone – extrato em planilha", "Stone"
    obrigatorias = (r"STONE INSTITUICAO DE PAGAMENTO", r"DATA \| TIPO \| LANCAMENTO")


@registrar
class AbcPlanilha(LayoutPlanilha):
    id, nome, banco = "abc_xlsx", "Banco ABC – planilha", "Banco ABC"
    obrigatorias = (r"OPERACAO \| VALOR( \(R\$\))? \| SALDO DIARIO|BANCO ABC",)


@registrar
class BanestesPlanilha(LayoutPlanilha):
    id, nome, banco = "banestes_xlsx", "Banestes – planilha", "Banestes"
    obrigatorias = (r"BANESTES",)
    # cobrança bloqueada é só informativa: o crédito entra depois como "Liberação Depósito Bloqueado"
    perfil = PerfilPlanilha(ignorar=r"^LIQUIDO COBRANCA BLOQUEADO|^LIQ\. COBRANCA \(BLOQ\.\)")


@registrar
class ContaSimplesPlanilha(LayoutPlanilha):
    id, nome, banco = "conta_simples_xlsx", "Conta Simples – planilha", "Conta Simples"
    obrigatorias = (r"NOME DO CARTAO", r"CREDITO R\$ \| DEBITO R\$")


@registrar
class ExtratoPlanilhaGenerico(LayoutPlanilha):
    """Qualquer planilha com tabela Data + Valor (ou Crédito/Débito): confiança mínima, só
    usado quando nenhum layout específico reconheceu o arquivo."""

    id, nome, banco = "planilha_generica", "Planilha de extrato (layout genérico)", ""
    proibidas = _NAO_EXTRATO

    def detectar(self, amostra: FileSample) -> float:
        if not self.aceita_tipo(amostra) or any(__import__("re").search(p, amostra.texto_normalizado) for p in self.proibidas):
            return 0.0
        return 0.6 if self.tem_tabela(amostra) else 0.0
