"""OFX (SGML 1.x e XML 2.x) — padrão aberto usado por vários bancos.

Amostras analisadas: tags uma por linha, tudo em uma linha com tags de fechamento e
formato compacto sem fechamento; valores com vírgula ou ponto decimal. Em todas o sinal de
TRNAMT coincide com TRNTYPE (CREDIT/DEBIT), então o sinal do valor decide; TRNTYPE só é
usado quando o valor vem sem sinal.
"""
from __future__ import annotations

import re

from extratos_app.detection.sniffer import OFX, FileSample
from extratos_app.models import ENTRADA, SAIDA, ErroLinha, Movimento, ResultadoImportacao
from extratos_app.parsers.base import LayoutParser, registrar
from extratos_app.services.normalizers import limpar_texto, parse_data, parse_valor

_TRANSACAO = re.compile(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", re.S | re.I)
TIPOS_DEBITO = {"DEBIT", "PAYMENT", "CHECK", "FEE", "SRVCHG", "ATM", "POS", "XFER_OUT", "DIRECTDEBIT", "CASH"}
TIPOS_CREDITO = {"CREDIT", "DEP", "INT", "DIV", "DIRECTDEP"}


def _tag(bloco: str, nome: str) -> str:
    m = re.search(rf"<{nome}>([^<\r\n]*)", bloco, re.I)
    return limpar_texto(m.group(1)) if m else ""


@registrar
class OfxParser(LayoutParser):
    id = "ofx"
    nome = "OFX (padrão bancário)"
    tipos = frozenset({OFX})

    def detectar(self, amostra: FileSample) -> float:
        if not self.aceita_tipo(amostra):
            return 0.0
        return 0.95 if "<STMTTRN>" in amostra.texto.upper() else 0.7

    def parsear(self, amostra: FileSample) -> ResultadoImportacao:
        texto = amostra.texto
        res = ResultadoImportacao(arquivo=amostra.caminho.name, layout_id=self.id, layout_nome=self.nome)
        banco = _tag(texto, "BANKID") or _tag(texto, "ORG")
        conta = _tag(texto, "ACCTID")
        res.banco, res.conta = banco, conta
        saldo = parse_valor(_tag(texto, "BALAMT"))
        res.saldo_final = saldo

        for n, m in enumerate(_TRANSACAO.finditer(texto), start=1):
            bloco = m.group(1)
            tipo_ofx = _tag(bloco, "TRNTYPE").upper()
            valor = parse_valor(_tag(bloco, "TRNAMT"))
            data = parse_data(_tag(bloco, "DTPOSTED")[:8])
            if valor is None or data is None:
                res.erros.append(ErroLinha(n, "Valor ou data inválidos na transação OFX", limpar_texto(bloco)[:200]))
                continue
            if valor == 0:
                res.ignorados += 1
                continue
            texto_valor = _tag(bloco, "TRNAMT")
            if texto_valor.startswith("-"):
                tipo = SAIDA
            elif tipo_ofx in TIPOS_DEBITO and not texto_valor.startswith("+"):
                tipo = SAIDA
            else:
                tipo = ENTRADA
            memo = _tag(bloco, "MEMO")
            nome = _tag(bloco, "NAME")
            descricao = memo if not nome or nome in memo else f"{nome} {memo}".strip()
            res.movimentos.append(
                Movimento(
                    data=data,
                    descricao=descricao,
                    valor=abs(valor),
                    tipo=tipo,
                    documento=_tag(bloco, "CHECKNUM") or _tag(bloco, "REFNUM"),
                    historico=tipo_ofx,
                    identificador=_tag(bloco, "FITID"),
                    conta=conta,
                    linha_origem=n,
                )
            )
        if not res.movimentos and not res.erros:
            res.avisos.append("O arquivo OFX não contém transações.")
        return res
