"""Validações comuns aplicadas a qualquer layout depois do parsing."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from extratos_app.models import ErroLinha, ResultadoImportacao
from extratos_app.services.normalizers import formatar_moeda

TOLERANCIA = Decimal("0.05")


def validar(res: ResultadoImportacao) -> ResultadoImportacao:
    validos = []
    for m in res.movimentos:
        if m.data is None:
            res.erros.append(ErroLinha(m.linha_origem, "Data inválida", m.descricao))
        elif m.valor is None or m.valor < 0:
            res.erros.append(ErroLinha(m.linha_origem, "Valor inválido", m.descricao))
        elif m.valor == 0:
            res.ignorados += 1
        else:
            validos.append(m)
    res.movimentos = validos

    chaves = Counter((m.data, m.valor, m.tipo, m.documento, m.descricao) for m in res.movimentos)
    repetidos = sum(n - 1 for n in chaves.values() if n > 1)
    if repetidos:
        res.avisos.append(
            f"{repetidos} lançamento(s) repetido(s) (mesma data, valor, documento e descrição) — mantidos, confira se procede."
        )
    if not res.conferencia:
        res.conferencia = conferir_saldos(res)
    return res


def conferir_saldos(res: ResultadoImportacao) -> str:
    """Confere os lançamentos contra os saldos informados no próprio arquivo.

    1) saldo inicial + entradas - saídas = saldo final;
    2) senão, cada trecho entre dois saldos consecutivos do mesmo tipo (saldo do dia, saldo
       conta+aplicação...) precisa bater com os lançamentos do trecho.
    """
    if not res.movimentos:
        return "sem saldos"
    if res.saldo_inicial is not None and res.saldo_final is not None:
        esperado = res.saldo_inicial + res.diferenca
        if abs(esperado - res.saldo_final) <= TOLERANCIA:
            return "ok"
    # séries por rótulo só valem com 3+ trechos (evita "ok" por coincidência)
    trechos = [t for k, t in res.trechos.items() if t[1] >= (3 if k.startswith("rotulo:") else 2)]
    if any(certos == total for certos, total in trechos):
        return "ok"
    if res.saldo_inicial is None or res.saldo_final is None:
        if not trechos:
            return "sem saldos"
    melhor = max(trechos, key=lambda t: t[0] / t[1], default=None)
    detalhe = f" ({melhor[0]} de {melhor[1]} trechos entre saldos conferem)" if melhor else ""
    if res.saldo_inicial is not None and res.saldo_final is not None:
        esperado = res.saldo_inicial + res.diferenca
        return f"divergente: calculado {formatar_moeda(esperado)}, arquivo {formatar_moeda(res.saldo_final)}{detalhe}"
    return f"divergente{detalhe}"
