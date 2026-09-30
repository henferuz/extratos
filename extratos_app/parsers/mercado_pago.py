"""Relatório de liberações da conta Mercado Pago (XLSX/CSV).

É um extrato de conta, não um relatório de vendas: cada linha credita ou debita o saldo
disponível (vendas, reservas, saques, reembolsos). A primeira linha traz o saldo inicial
(``initial_available_balance``) e a última, ``total``, o saldo final:
saldo inicial + créditos − débitos = saldo final.
"""
from __future__ import annotations

import re
from decimal import Decimal

from extratos_app.detection.sniffer import CSV, XLS, XLSX, FileSample
from extratos_app.models import ENTRADA, SAIDA, ErroLinha, Movimento, ResultadoImportacao
from extratos_app.parsers.base import LayoutParser, registrar
from extratos_app.parsers.planilha_base import abas_completas
from extratos_app.services.normalizers import limpar_texto, parse_data, parse_valor, sem_acentos

_DESCRICOES = {
    "payment": "Venda",
    "payout": "Saque",
    "refund": "Reembolso",
    "reserve_for_payment": "Reserva para pagamento",
    "reserve_for_payout": "Reserva para saque",
    "reserve_for_refund": "Reserva para reembolso",
}
_COLUNAS = {
    "data": "DATA DE LIBERACAO",
    "documento": "ID DA OPERACAO NO MERCADO PAGO",
    "referencia": "CODIGO DE REFERENCIA",
    "registro": "TIPO DE REGISTRO",
    "descricao": "DESCRICAO",
    "credito": "VALOR LIQUIDO CREDITADO",
    "debito": "VALOR LIQUIDO DEBITADO",
    "meio": "MEIO DE PAGAMENTO",
}


def _norm(valor: object) -> str:
    return " ".join(sem_acentos(str(valor or "")).upper().split())


@registrar
class MercadoPagoLiberacoes(LayoutParser):
    id, nome, banco = "mercado_pago_liberacoes", "Mercado Pago – relatório de liberações", "Mercado Pago"
    tipos = frozenset({XLSX, XLS, CSV})

    def detectar(self, amostra: FileSample) -> float:
        if not self.aceita_tipo(amostra):
            return 0.0
        texto = amostra.texto_normalizado
        # Acima do perfil de cartão Mercado Pago (0,95) para não haver empate.
        assinatura = ("VALOR LIQUIDO CREDITADO", "VALOR LIQUIDO DEBITADO", "TIPO DE REGISTRO", "DATA DE LIBERACAO")
        return 0.98 if all(item in texto for item in assinatura) else 0.0

    def parsear(self, amostra: FileSample) -> ResultadoImportacao:
        resultado = ResultadoImportacao(amostra.caminho.name, layout_id=self.id, layout_nome=self.nome, banco=self.banco)
        for linhas in abas_completas(amostra).values():
            cabecalho = next(
                (i for i, linha in enumerate(linhas[:80]) if _COLUNAS["credito"] in [_norm(c) for c in linha]),
                None,
            )
            if cabecalho is None:
                continue
            nomes = [_norm(c) for c in linhas[cabecalho]]
            col = {campo: nomes.index(nome) for campo, nome in _COLUNAS.items() if nome in nomes}

            def cel(linha: list, campo: str) -> object:
                indice = col.get(campo)
                return linha[indice] if indice is not None and indice < len(linha) else None

            for numero, linha in enumerate(linhas[cabecalho + 1 :], start=cabecalho + 2):
                registro = _norm(cel(linha, "registro"))
                credito = parse_valor(cel(linha, "credito")) or Decimal("0")
                debito = parse_valor(cel(linha, "debito")) or Decimal("0")
                if registro == "INITIAL_AVAILABLE_BALANCE":
                    resultado.saldo_inicial = credito - debito
                    resultado.ignorados += 1
                    continue
                if registro == "TOTAL":
                    resultado.saldo_final = credito - debito
                    resultado.ignorados += 1
                    continue
                if not credito and not debito:
                    continue
                data = parse_data(cel(linha, "data"))
                if data is None:
                    resultado.erros.append(ErroLinha.de_linha(numero, "Data inválida", linha))
                    continue
                codigo = limpar_texto(cel(linha, "descricao"))
                referencia = limpar_texto(cel(linha, "referencia"))
                partes = [_DESCRICOES.get(codigo, codigo) or "Lançamento"]
                # Referência útil ("Venda presencial"); códigos QR longos não descrevem nada.
                if referencia and not re.match(r"MP-QR-", referencia, re.IGNORECASE):
                    partes.append(referencia)
                extras = {"Meio de pagamento": limpar_texto(cel(linha, "meio"))} if limpar_texto(cel(linha, "meio")) else {}
                for valor, tipo in ((credito, ENTRADA), (debito, SAIDA)):
                    if valor:
                        resultado.movimentos.append(Movimento(
                            data, " - ".join(partes), abs(valor), tipo,
                            documento=limpar_texto(cel(linha, "documento")), linha_origem=numero, extras=dict(extras),
                        ))
        return resultado
