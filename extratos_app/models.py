"""Estrutura padronizada usada por todos os parsers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

ENTRADA = "ENTRADA"
SAIDA = "SAIDA"
TipoMovimento = Literal["ENTRADA", "SAIDA"]


@dataclass
class Movimento:
    data: date
    descricao: str
    valor: Decimal  # sempre positivo; o sentido fica em `tipo`
    tipo: TipoMovimento
    documento: str = ""
    historico: str = ""
    identificador: str = ""
    conta: str = ""
    origem: str = ""
    destino: str = ""
    extras: dict[str, str] = field(default_factory=dict)
    linha_origem: int | None = None


@dataclass
class ErroLinha:
    linha: int | None
    motivo: str
    conteudo: str = ""

    @classmethod
    def de_linha(cls, linha: int | None, motivo: str, conteudo: object = "") -> "ErroLinha":
        texto = " | ".join(str(v) for v in conteudo if v not in (None, "")) if isinstance(conteudo, (list, tuple)) else str(conteudo or "")
        return cls(linha, motivo, " ".join(texto.split())[:200])


@dataclass
class ResultadoImportacao:
    arquivo: str
    layout_id: str = ""
    layout_nome: str = ""
    banco: str = ""
    conta: str = ""
    saldo_inicial: Decimal | None = None
    saldo_final: Decimal | None = None
    movimentos: list[Movimento] = field(default_factory=list)
    erros: list[ErroLinha] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    ignorados: int = 0  # linhas descartadas de propósito (saldos, bloqueios...)
    conferencia: str = ""  # resultado da conferência de saldos
    trechos: dict[str, tuple[int, int]] = field(default_factory=dict)  # tipo de saldo -> (certos, total)
    trechos_falhos: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # linhas dos saldos que não batem

    @property
    def entradas(self) -> list[Movimento]:
        return [m for m in self.movimentos if m.tipo == ENTRADA]

    @property
    def saidas(self) -> list[Movimento]:
        return [m for m in self.movimentos if m.tipo == SAIDA]

    @property
    def total_entradas(self) -> Decimal:
        return sum((m.valor for m in self.entradas), Decimal("0"))

    @property
    def total_saidas(self) -> Decimal:
        return sum((m.valor for m in self.saidas), Decimal("0"))

    @property
    def diferenca(self) -> Decimal:
        return self.total_entradas - self.total_saidas

    @property
    def periodo(self) -> tuple[date, date] | None:
        if not self.movimentos:
            return None
        datas = [m.data for m in self.movimentos]
        return min(datas), max(datas)


class ArquivoNaoReconhecido(Exception):
    """Arquivo vazio, inválido ou de layout desconhecido."""
