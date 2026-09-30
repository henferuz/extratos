"""Base dos layouts de planilha (XLSX, XLS, CSV)."""
from __future__ import annotations

from extratos_app.detection.sniffer import CSV, XLS, XLSX, FileSample, ler_csv, ler_xls, ler_xlsx
from extratos_app.engine.planilha import MotorPlanilha, PerfilPlanilha
from extratos_app.models import ResultadoImportacao
from extratos_app.parsers.base import LayoutPorAssinatura


def abas_completas(amostra: FileSample) -> dict[str, list[list]]:
    """Todas as linhas de todas as abas, com valores brutos (datas e números do Excel)."""
    if amostra.tipo == XLSX:
        return ler_xlsx(amostra.caminho, None, valores_brutos=True)
    if amostra.tipo == XLS:
        return ler_xls(amostra.caminho, None, valores_brutos=True)
    return {"csv": ler_csv(amostra.bytes)}


class LayoutPlanilha(LayoutPorAssinatura):
    tipos = frozenset({XLSX, XLS, CSV})
    perfil: PerfilPlanilha = PerfilPlanilha()
    banco: str = ""

    def tem_tabela(self, amostra: FileSample) -> bool:
        motor = MotorPlanilha(self.perfil)
        return any(motor.achar_cabecalho(linhas) for linhas in amostra.planilhas.values())

    def detectar(self, amostra: FileSample) -> float:
        nota = super().detectar(amostra)
        return nota if nota and self.tem_tabela(amostra) else 0.0

    def parsear(self, amostra: FileSample) -> ResultadoImportacao:
        res = ResultadoImportacao(arquivo=amostra.caminho.name, layout_id=self.id, layout_nome=self.nome, banco=self.banco)
        return MotorPlanilha(self.perfil).processar(abas_completas(amostra), res)
