"""Perfis de adquirentes e fallback para planilhas de cartões."""
from __future__ import annotations

import re

from extratos_app.detection.sniffer import CSV, XLS, XLSX, FileSample
from extratos_app.engine.cartoes import MotorCartoes, PerfilCartao
from extratos_app.models import ResultadoImportacao
from extratos_app.parsers.base import LayoutParser, registrar
from extratos_app.parsers.planilha_base import abas_completas
from extratos_app.services.normalizers import parse_data, parse_valor, sem_acentos


class _CartaoParser(LayoutParser):
    tipos = frozenset({XLSX, XLS, CSV})
    aliases: tuple[str, ...] = ()
    grupo = "A"

    @staticmethod
    def _linhas_de_cabecalho(amostra: FileSample) -> list[str]:
        """Exige uma linha de cabeçalho de adquirente, não só palavras do histórico."""
        padroes = (
            r"BRUTO|VLR[. ]?VDA|VALOR DA VENDA|VALORBRUTOPARCELA|V[.] ORIGINAL|VL[.]BRUTO|ENTRADA BRUTA|QUANTIA TOTAL|VALOR CREDITO|VALOR A VISTA|VALOR COMPRA|PRECO ORIGINAL|HOMOLOGADO|AMOUNT|PRICE|VALOR$|VALOR R[$]$",
            r"LIQUIDO|VLR[. ]?LIQ|VALORLIQUIDOPARCELA|V[.] RECEBIMENTO|VL[.]LIQUIDO|A RECEBER|PAGO|AMOUNT RECEIVED|PRICE SELLER",
            r"TAXA|MDR|DESCONTO|TARIFA|TX[.] ADM|COMISSAO|VALORDESCONTOPARCELA|VL[.]COMISSAO|FEE|TAX",
            r"NSU|AUTORIZACAO|BANDEIRA|DATA|DATE|DATA DE PAGAMENTO|DATA DA VENDA|DATA[/ ]HORA|DATATRANSACAO|DATA DA OPERACAO|DATA OPERACAO|EMISSAO|D[.] MOVIMENTO|N[.]? CARTAO|PAYOUT|TRANSACTION",
        )
        candidatas = []
        for linhas in amostra.planilhas.values():
            for linha in linhas[:80]:
                texto = [sem_acentos(str(c or "")).upper() for c in linha]
                celulas = [c for c in linha if c not in (None, "")]
                contem_valor = any(
                    parse_data(c) is not None or parse_valor(c) is not None for c in celulas
                )
                cabecalho_senff = len(celulas) == 2 and {
                    sem_acentos(str(c)).strip().upper() for c in celulas
                } == {"DATA", "HOMOLOGADO"}
                if (len(celulas) < 3 and not cabecalho_senff) or contem_valor:
                    continue
                fortes = sum(any(re.search(padrao, celula) for celula in texto) for padrao in padroes)
                if fortes >= 2:
                    candidatas.append(" ".join(texto))
        return candidatas

    @classmethod
    def _tem_colunas_cartao(cls, amostra: FileSample) -> bool:
        return bool(cls._linhas_de_cabecalho(amostra))

    @classmethod
    def _nomes_de_pessoas(cls, amostra: FileSample) -> tuple[str, list[str]]:
        """Separa as colunas de nome de cliente/portador do resto da amostra.

        Devolve o texto sem essas colunas e os nomes encontrados nelas: um cliente chamado
        "Mercado Pago" não identifica a adquirente do arquivo.
        """
        cabecalhos = set(cls._linhas_de_cabecalho(amostra))
        partes: list[str] = []
        nomes: list[str] = []
        for linhas in amostra.planilhas.values():
            colunas_nome: set[int] = set()
            for linha in linhas:
                celulas = [sem_acentos(str(c or "")).upper() for c in linha]
                partes += [c for i, c in enumerate(celulas) if i not in colunas_nome]
                nomes += [c for i, c in enumerate(celulas) if i in colunas_nome]
                if " ".join(celulas) in cabecalhos:
                    colunas_nome = {
                        i for i, c in enumerate(celulas)
                        if re.fullmatch(r"(NOME( DO)?( CLIENTE| PORTADOR.*)?|CLIENTE|PORTADOR.*)", c.strip())
                    }
        return " ".join(" ".join(partes).split()), nomes

    def _cita_adquirente(self, amostra: FileSample) -> bool:
        sem_nomes, nomes = self._nomes_de_pessoas(amostra)
        for alias in self.aliases:
            padrao = rf"\b{re.escape(alias)}\b"
            if not re.search(padrao, amostra.texto_normalizado):
                continue
            # Só no nome de uma pessoa (e em nenhum outro lugar da amostra) não conta.
            if re.search(padrao, sem_nomes) or not any(re.search(padrao, nome) for nome in nomes):
                return True
        return False

    def detectar(self, amostra: FileSample) -> float:
        if not self.aceita_tipo(amostra):
            return 0.0
        if not self._tem_colunas_cartao(amostra):
            return 0.0
        texto = amostra.texto_normalizado
        cabecalhos = " ".join(self._linhas_de_cabecalho(amostra))
        indicadores = sum(
            bool(re.search(padrao, texto))
            for padrao in (
                r"BRUTO|VALOR BRUTO|VALOR DA VENDA|VLR[. ]?VDA|VALORBRUTOPARCELA|V[.] ORIGINAL|VL[.]BRUTO|ENTRADA BRUTA|QUANTIA TOTAL|VALOR CREDITO|VALOR A VISTA|VALOR COMPRA|PRECO ORIGINAL|HOMOLOGADO|VALOR$|PRICE|AMOUNT|ENTRADA",
                r"LIQUIDO|VALOR LIQUIDO|VLR[. ]?LIQ|VALOR DE PAGAMENTO|VALORLIQUIDOPARCELA|V[.] RECEBIMENTO|VL[.]LIQUIDO|A RECEBER|PAGO|AMOUNT RECEIVED|PRICE SELLER",
                r"TAXA|MDR|DESCONTO|COMISSAO|TX[. ]?ADM|VALORDESCONTOPARCELA|VL[.]COMISSAO|FEE|TAX",
                r"NSU|AUTORIZACAO|BANDEIRA|C6PAY|EMISSAO|DATA|DATE|DATA[/ ]HORA|DATATRANSACAO|DATA DA OPERACAO|DATA OPERACAO|N[.]? CARTAO|PAYOUT|TRANSACTION",
            )
        )
        tem_alias = self._cita_adquirente(amostra)
        if self.aliases and tem_alias and not re.search(r"\bSALDO\b", cabecalhos):
            return 0.95 if indicadores >= 2 else 0.85
        return 0.0

    def parsear(self, amostra: FileSample) -> ResultadoImportacao:
        resultado = ResultadoImportacao(amostra.caminho.name, layout_id=self.id, layout_nome=self.nome, banco=self.banco)
        return MotorCartoes(PerfilCartao(grupo=self.grupo)).processar(abas_completas(amostra), resultado)


@registrar
class CieloCartao(_CartaoParser):
    id, nome, banco = "cielo_cartao", "Cielo – cartão", "Cielo"
    aliases = ("CIELO",)


@registrar
class StoneCartao(_CartaoParser):
    id, nome, banco = "stone_cartao", "Stone – cartão", "Stone"
    aliases = ("STONE",)


@registrar
class GetnetCartao(_CartaoParser):
    id, nome, banco = "getnet_cartao", "Getnet – cartão", "Getnet"
    aliases = ("GETNET",)


@registrar
class RedeSipagCartao(_CartaoParser):
    id, nome, banco = "rede_sipag_cartao", "Rede/Sipag – cartão", "Rede/Sipag"
    aliases = ("REDE", "SIPAG")


@registrar
class PagSeguroCartao(_CartaoParser):
    id, nome, banco = "pagseguro_cartao", "PagSeguro/PagBank – cartão", "PagSeguro/PagBank"
    aliases = ("PAGSEGURO", "PAGBANK")
    grupo = "B"


@registrar
class MercadoPagoCartao(_CartaoParser):
    id, nome, banco = "mercado_pago_cartao", "Mercado Pago – cartão", "Mercado Pago"
    aliases = ("MERCADO PAGO", "MERCADO LIVRE")
    grupo = "B"


@registrar
class SafraCartao(_CartaoParser):
    id, nome, banco = "safra_cartao", "Safra – cartão", "Safra"
    aliases = ("SAFRA",)


@registrar
class SicrediCartao(_CartaoParser):
    id, nome, banco = "sicredi_cartao", "Sicredi – cartão", "Sicredi"
    aliases = ("SICREDI",)


@registrar
class CartaoGenerico(_CartaoParser):
    id, nome, banco = "cartao_generico", "Cartão – planilha genérica", ""

    def detectar(self, amostra: FileSample) -> float:
        if not self.aceita_tipo(amostra):
            return 0.0
        if not self._tem_colunas_cartao(amostra):
            return 0.0
        texto = amostra.texto_normalizado
        cabecalhos = " ".join(self._linhas_de_cabecalho(amostra))
        inicio = " ".join(
            " ".join(sem_acentos(str(c or "")).upper() for c in linha)
            for linhas in amostra.planilhas.values()
            for linha in linhas[:15]
        )
        indicadores = sum(
            bool(re.search(padrao, texto))
            for padrao in (
                r"BRUTO|VALOR BRUTO|VALOR DA VENDA|VLR[. ]?VDA|V[.] ORIGINAL|V[.] RECEBIMENTO|VALOR CREDITO|VALOR A VISTA|VALOR COMPRA|PRECO ORIGINAL|HOMOLOGADO|VALOR\b|PRICE|AMOUNT|ENTRADA",
                r"LIQUIDO|VALOR LIQUIDO|VLR[. ]?LIQ|VALOR DE PAGAMENTO|PAGO|AMOUNT RECEIVED|PRICE SELLER",
                r"TAXA|MDR|DESCONTO|COMISSAO|TX[. ]?ADM|FEE|TAX",
                r"NSU|AUTORIZACAO|BANDEIRA|C6PAY|EMISSAO|DATA\b|DATE\b|D[.] LANCAMENTO|TRANSACTION|TRANSACAO",
                r"ADQUIRENTE|CARTAO",
            )
        )
        marcador = bool(
            re.search(
                r"CARTAO|BANDEIRA|NSU|PARCELA|TICKET|ADQUIRENTE|VENDA|COMPRA|TRANSACTION|TRANSACAO|PAYOUT|FEE|TAXA|MDR|TX[.]? ADM|PRODUTO|HOMOLOGADO",
                cabecalhos,
            )
            or re.search(r"TICKET", inicio)
        )
        return 0.66 if indicadores >= 2 and marcador else 0.0

    def parsear(self, amostra: FileSample) -> ResultadoImportacao:
        resultado = ResultadoImportacao(amostra.caminho.name, layout_id=self.id, layout_nome=self.nome)
        return MotorCartoes(PerfilCartao(grupo="A")).processar(abas_completas(amostra), resultado)
