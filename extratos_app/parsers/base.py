"""Contrato comum dos parsers e registro de layouts.

Para suportar um layout novo basta criar uma subclasse de `LayoutParser` decorada com
`@registrar` em qualquer módulo do pacote `parsers` — detector e interface não mudam.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from extratos_app.detection.sniffer import FileSample
from extratos_app.models import ResultadoImportacao

_REGISTRO: list["LayoutParser"] = []


def registrar(cls: type["LayoutParser"]) -> type["LayoutParser"]:
    _REGISTRO.append(cls())
    return cls


def parsers_registrados() -> list["LayoutParser"]:
    return list(_REGISTRO)


class LayoutParser(ABC):
    id: str = ""
    nome: str = ""
    tipos: frozenset[str] = frozenset()  # tipos reais aceitos (pdf, xlsx, texto...)

    def aceita_tipo(self, amostra: FileSample) -> bool:
        return not self.tipos or amostra.tipo in self.tipos

    @abstractmethod
    def detectar(self, amostra: FileSample) -> float:
        """Confiança de 0 a 1 de que o arquivo é deste layout (baseado no conteúdo)."""

    @abstractmethod
    def parsear(self, amostra: FileSample) -> ResultadoImportacao:
        ...


class LayoutPorAssinatura(LayoutParser):
    """Detecção por assinaturas de texto (regex sobre o texto normalizado: maiúsculo, sem acento).

    - `obrigatorias`: todas precisam aparecer;
    - `opcionais`: cada uma que aparece aumenta a confiança (desempata variações do mesmo banco);
    - `proibidas`: se alguma aparece, não é este layout.
    """

    obrigatorias: tuple[str, ...] = ()
    opcionais: tuple[str, ...] = ()
    proibidas: tuple[str, ...] = ()

    def detectar(self, amostra: FileSample) -> float:
        if not self.aceita_tipo(amostra):
            return 0.0
        texto = amostra.texto_normalizado
        if not texto:
            return 0.0
        if any(re.search(p, texto) for p in self.proibidas):
            return 0.0
        if not all(re.search(p, texto) for p in self.obrigatorias):
            return 0.0
        base = 0.6 + 0.02 * len(self.obrigatorias)
        if self.opcionais:
            base += 0.3 * sum(bool(re.search(p, texto)) for p in self.opcionais) / len(self.opcionais)
        return min(base, 0.99)
