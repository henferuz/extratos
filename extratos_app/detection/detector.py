"""FileDetector: escolhe o parser de maior confiança entre os layouts registrados."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from pathlib import Path

from extratos_app import parsers as pacote_parsers
from extratos_app.detection.sniffer import DESCONHECIDO, FileSample
from extratos_app.models import ArquivoNaoReconhecido
from extratos_app.parsers.base import LayoutParser, parsers_registrados
from extratos_app.services.validator import validar

CONFIANCA_MINIMA = 0.6
_carregado = False
_LOGGER = logging.getLogger(__name__)


def _carregar_parsers() -> None:
    global _carregado
    if _carregado:
        return
    nomes = {f"{pacote_parsers.__name__}.{modulo}" for modulo in pacote_parsers.MODULOS}
    # A lista declarada vale no executável; o pkgutil ainda pega módulos novos no código-fonte.
    nomes |= {mod.name for mod in pkgutil.walk_packages(pacote_parsers.__path__, pacote_parsers.__name__ + ".")}
    for nome in sorted(nomes):
        importlib.import_module(nome)
    _carregado = True


@dataclass
class Deteccao:
    amostra: FileSample
    parser: LayoutParser
    confianca: float
    resultado: ResultadoImportacao | None = None


class FileDetector:
    def __init__(self) -> None:
        _carregar_parsers()
        self.parsers = parsers_registrados()

    def detectar(self, caminho: Path | str, amostra: FileSample | None = None) -> Deteccao:
        caminho = Path(caminho)
        if not caminho.is_file():
            raise ArquivoNaoReconhecido("Arquivo não encontrado.")
        amostra = amostra or FileSample.ler(caminho)
        if amostra.tamanho == 0 or not amostra.bytes.strip():
            raise ArquivoNaoReconhecido("O arquivo está vazio.")
        if (
            amostra.bytes.startswith(b"\xd0\xcf\x11\xe0")
            and "EncryptedPackage".encode("utf-16-le") in amostra.bytes
            and (
                b"EncryptionInfo" in amostra.bytes
                or "EncryptionInfo".encode("utf-16-le") in amostra.bytes
            )
        ):
            raise ArquivoNaoReconhecido("Arquivo protegido por senha — remova a senha e tente novamente.")
        if amostra.tipo == DESCONHECIDO:
            if amostra.bytes.startswith(b"PK"):
                raise ArquivoNaoReconhecido("Arquivo compactado — extraia o conteúdo antes de importar.")
            raise ArquivoNaoReconhecido("Formato de arquivo não reconhecido (esperado PDF, OFX, TXT, CSV, XLS ou XLSX).")
        if amostra.tipo == "pdf":
            _ = amostra.texto
            if amostra.protegido_por_senha:
                raise ArquivoNaoReconhecido("Arquivo protegido por senha — remova a senha e tente novamente.")

        pontuados = sorted(
            ((p.detectar(amostra), p) for p in self.parsers if p.aceita_tipo(amostra)),
            key=lambda par: par[0],
            reverse=True,
        )
        if not pontuados or pontuados[0][0] < CONFIANCA_MINIMA:
            if amostra.tipo == "pdf" and not amostra.texto.strip():
                raise ArquivoNaoReconhecido("PDF sem texto (provavelmente digitalizado/imagem) — não é possível ler.")
            raise ArquivoNaoReconhecido("Layout não reconhecido: este modelo de arquivo ainda não é suportado.")
        confianca, parser = pontuados[0]
        resultados: dict[LayoutParser, ResultadoImportacao | None] = {}
        empatados = [item for item in pontuados if confianca - item[0] < 0.02]
        if len(empatados) > 1:
            escolhido = None
            for nota, candidato in empatados:
                try:
                    resultado = validar(candidato.parsear(amostra))
                except Exception:  # noqa: BLE001 - falha de um candidato não invalida o empate
                    resultados[candidato] = None
                    continue
                resultados[candidato] = resultado
                if resultado.conferencia == "ok":
                    escolhido = (nota, candidato, resultado)
                    break
            if escolhido is not None:
                confianca, parser, resultado = escolhido
            else:
                _LOGGER.warning(
                    "Layout ambíguo para %s; escolhendo %s (nota %.3f)",
                    caminho,
                    parser.id,
                    confianca,
                )
        if parser.id.endswith("_cartao"):
            # Assinaturas de adquirentes podem aparecer em planilhas bancárias
            # (por exemplo, "rede" em uma coluna de descrição). Se o candidato
            # de cartão não encontra lançamentos, tente o próximo parser real
            # antes de devolver uma detecção que inevitavelmente falharia.
            if parser not in resultados:
                try:
                    resultados[parser] = validar(parser.parsear(amostra))
                except Exception:  # noqa: BLE001 - candidato principal inválido
                    resultados[parser] = None
            principal = resultados[parser]
            if principal is not None and principal.movimentos:
                return Deteccao(amostra, parser, confianca, principal)
            alternativas = [
                item for item in pontuados
                if item[0] >= CONFIANCA_MINIMA and not item[1].id.endswith("_cartao")
            ] + [
                item for item in pontuados
                if item[0] >= CONFIANCA_MINIMA and item[1].id.endswith("_cartao")
            ]
            for nota, candidato in alternativas:
                if candidato is parser:
                    continue
                if candidato in resultados:
                    resultado = resultados[candidato]
                    if resultado is not None and resultado.movimentos:
                        confianca, parser = nota, candidato
                        break
                    continue
                try:
                    resultado = validar(candidato.parsear(amostra))
                except Exception:  # noqa: BLE001 - candidato alternativo
                    resultados[candidato] = None
                    continue
                resultados[candidato] = resultado
                if resultado.movimentos:
                    confianca, parser = nota, candidato
                    break
        return Deteccao(amostra, parser, confianca, resultados.get(parser))
