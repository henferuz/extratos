"""Formatação pura dos resultados para a interface, sem dependência de Tkinter."""
from __future__ import annotations

from collections.abc import Iterable

from extratos_app.models import ArquivoNaoReconhecido, ResultadoImportacao
from extratos_app.services.normalizers import formatar_moeda


def resumo_para_exibicao(res: ResultadoImportacao) -> list[tuple[str, str, str]]:
    periodo = "—"
    if res.periodo:
        periodo = f"{res.periodo[0]:%d/%m/%Y} a {res.periodo[1]:%d/%m/%Y}"
    return [
        ("Arquivo", res.arquivo, "normal"),
        ("Tipo identificado", res.layout_nome or res.layout_id or "—", "normal"),
        ("Período", periodo, "normal"),
        ("Registros encontrados", str(len(res.movimentos)), "normal"),
        ("Entradas", str(len(res.entradas)), "entrada"),
        ("Saídas", str(len(res.saidas)), "saida"),
        ("Total de entradas", formatar_moeda(res.total_entradas), "entrada"),
        ("Total de saídas", formatar_moeda(res.total_saidas), "saida"),
        ("Diferença", formatar_moeda(res.diferenca), "normal"),
        ("Saldo inicial", formatar_moeda(res.saldo_inicial) if res.saldo_inicial is not None else "—", "normal"),
        ("Saldo final", formatar_moeda(res.saldo_final) if res.saldo_final is not None else "—", "normal"),
        ("Conferência", res.conferencia or "—", "ok" if res.conferencia == "ok" else "alerta"),
    ]


def mensagens_importacao(res: ResultadoImportacao) -> list[tuple[str, str]]:
    mensagens = [
        ("normal", f"Arquivo importado: {res.arquivo}."),
        ("normal", f"Layout identificado: {res.layout_nome or res.layout_id or '—'}."),
        ("normal", f"{len(res.movimentos)} registros encontrados."),
    ]
    if res.erros:
        mensagens.append(("aviso", f"{len(res.erros)} registros ignorados por inconsistência."))
    if res.conferencia == "ok":
        mensagens.append(("ok", "Conferência de saldos: ok."))
    elif res.conferencia.startswith("divergente"):
        mensagens.append(("aviso", f"Atenção: saldos divergentes — {res.conferencia}."))
    else:
        mensagens.append(("normal", f"Conferência de saldos: {res.conferencia or 'sem saldos'}."))
    return mensagens


def mensagem_erro(exc: Exception) -> str:
    if isinstance(exc, ArquivoNaoReconhecido):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "Não foi possível salvar: o arquivo está aberto em outro programa (feche o Excel e tente novamente)."
    if isinstance(exc, OSError):
        return f"Não foi possível salvar o arquivo: {exc}"
    return "Erro inesperado ao processar o arquivo. Detalhes no log técnico."
