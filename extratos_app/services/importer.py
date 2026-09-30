"""Orquestra: detectar -> parsear -> validar. É o único ponto que a interface chama."""
from __future__ import annotations

from pathlib import Path

from extratos_app.detection.detector import FileDetector
from extratos_app.detection.sniffer import FileSample
from extratos_app.models import ArquivoNaoReconhecido, ResultadoImportacao
from extratos_app.services.validator import validar

_detector: FileDetector | None = None


def detector() -> FileDetector:
    global _detector
    if _detector is None:
        _detector = FileDetector()
    return _detector


def importar(caminho: Path | str, amostra: FileSample | None = None) -> ResultadoImportacao:
    """Lança ArquivoNaoReconhecido quando o arquivo não pode ser processado."""
    deteccao = detector().detectar(caminho, amostra)
    # O detector devolve o resultado já validado quando precisou interpretar o arquivo.
    resultado = deteccao.resultado
    if resultado is None:
        try:
            resultado = deteccao.parser.parsear(deteccao.amostra)
        except ArquivoNaoReconhecido:
            raise
        except Exception as exc:  # noqa: BLE001 - arquivo corrompido não deve derrubar o programa
            raise ArquivoNaoReconhecido(f"Não foi possível ler o arquivo como {deteccao.parser.nome}: {exc}") from exc
        resultado = validar(resultado)
    if not resultado.movimentos:
        raise ArquivoNaoReconhecido(
            f"Arquivo identificado como {deteccao.parser.nome}, mas nenhum lançamento foi encontrado."
        )
    return resultado
