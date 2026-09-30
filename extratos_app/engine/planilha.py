"""Motor genérico para extratos em planilha (XLSX, XLS, CSV).

Regras tiradas das amostras (Itaú, Bradesco, Santander, Safra, Sicoob, Unicred, PagBank, Stone,
ABC, Banpará, Banestes, Conta Simples, HDT):

* a tabela começa numa linha de cabeçalho com Data + (Valor | Crédito/Débito); antes dela vêm
  dados da conta, que são ignorados;
* cada coluna é reconhecida pelo nome (lista de sinônimos abaixo); colunas não reconhecidas são
  preservadas como informação extra no Excel gerado;
* o sentido vem do sinal do valor, da coluna Crédito/Débito, de uma coluna de tipo
  ("Crédito", "Débito (-)", "D") ou, por último, da variação do saldo;
* datas podem vir como data do Excel, número serial, 'dd/mm/aaaa [hh:mm]' ou 'dd/mm';
* linhas sem data e sem valor logo abaixo de um lançamento são complemento do histórico;
* coluna "Tarifa" (Stone) é debitada à parte: vira uma saída própria.

A conferência de saldos e a inferência de sinal reaproveitam o motor de texto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from extratos_app.engine.texto import (
    SALDO_FORA_DA_CONTA,
    SALDO_INICIAL_PADRAO,
    MotorTexto,
    PerfilTexto,
    Evento,
)
from extratos_app.models import ErroLinha, ResultadoImportacao
from extratos_app.services.normalizers import limpar_texto, parse_data, parse_valor, sem_acentos

# sinônimos de cabeçalho (texto normalizado: maiúsculo, sem acento, sem "(R$)")
COLUNAS_PADRAO: dict[str, str] = {
    "data": r"^(DATA|DT\.?)( (DO |DE |DA )?(LANCAMENTO|MOVIMENTO|MOVIMENTACAO|MOV\.?|CONTABIL|RECEBIMENTO|TRANSACAO|VENDA|PAGAMENTO|CAPTURA))?$",
    "descricao": r"^(HISTORICOS?|DESCRICAO|LANCAMENTOS?|HISTORICO DE LANCAMENTOS|OPERACAO REALIZADA)$",
    "documento": r"^(DOCUMENTO|DOCTO\.?|DCTO\.?|DOC\.?|NRO\.? DOCUMENTO|N[O°º]\.? ?DOCUMENTO|NUMERO (DO )?DOCUMENTO|ID\.? DOC|NR\.? ?DOC\.?|NUMERO DOCUMENTO)$",
    "valor": r"^(VALOR|VALOR DO LANCAMENTO|VALOR (DA )?(VENDA|PAGAMENTO|TRANSACAO)|VALOR (BRUTO|LIQUIDO)|LANCAMENTOS?|MONTANTE|CREDITOS/DEBITOS)$",
    "credito": r"^(CREDITOS?|ENTRADAS?)$",
    "debito": r"^(DEBITOS?|SAIDAS?)$",
    "saldo": r"^(SALDO|SALDOS|SALDO DIARIO|SALDO DEPOIS|SALDO DO DIA)$",
    "tipo": r"^(TIPO DO LANCAMENTO|OPERACAO|MOVIMENTACAO|NATUREZA|D/C|C/D|TIPO)$",
    "complemento": r"^(COMPLEMENTO|DETALHES|CONTRAPARTE)$",
    "tarifa": r"^TARIFA$",
}
_SALDO = re.compile(r"^(S\s?A\s?L\s?D\s?O|SALDO|SDO\b|SLD\b)")
_DEBITO = re.compile(r"^(D|DEBITO|DEBITOS|SAIDA|SAIDAS|\(-\)|-)$|^DEBITO\s*\(-\)$")
_CREDITO = re.compile(r"^(C|CREDITO|CREDITOS|ENTRADA|ENTRADAS|\(\+\)|\+)$|^CREDITO\s*\(\+\)$")
_MOEDA = re.compile(r"\(?R\$\)?|\bUSD\b")


def _norm(v: object) -> str:
    return limpar_texto(sem_acentos(str(v or "")).upper())


def _cabecalho(v: object) -> tuple[str, bool]:
    texto = _norm(v)
    monetaria = bool(_MOEDA.search(texto))
    texto = limpar_texto(_MOEDA.sub(" ", texto)).strip(" :")
    return texto, monetaria


@dataclass
class PerfilPlanilha:
    colunas: dict[str, str] = field(default_factory=lambda: dict(COLUNAS_PADRAO))
    sem_sinal: str = "credito"
    debito_se: str | None = None  # regex sobre descrição/tipo que indica débito quando não há sinal
    credito_se: str | None = None
    ignorar: str | None = None  # linhas cuja descrição casar são descartadas
    saldo_fora_da_conta: str = SALDO_FORA_DA_CONTA
    min_colunas_cabecalho: int = 3


@dataclass
class _Mapa:
    linha: int
    colunas: dict[str, int]
    nomes: dict[int, str]


class MotorPlanilha:
    def __init__(self, perfil: PerfilPlanilha) -> None:
        self.p = perfil
        self._re = {k: re.compile(v) for k, v in perfil.colunas.items()}
        self._fora = re.compile(perfil.saldo_fora_da_conta)
        self._ini = re.compile(SALDO_INICIAL_PADRAO)

    # ----------------------------------------------------------- cabeçalho
    def achar_cabecalho(self, linhas: list[list], inicio: int = 0) -> _Mapa | None:
        for i in range(inicio, min(len(linhas), inicio + 80)):
            mapa = self._mapear(linhas[i], i)
            if mapa:
                return mapa
        return None

    def _mapear(self, linha: list, i: int) -> _Mapa | None:
        colunas: dict[str, int] = {}
        nomes: dict[int, str] = {}
        preenchidas = 0
        for j, v in enumerate(linha):
            if v in (None, "") or isinstance(v, (int, float, datetime, date)):
                continue
            preenchidas += 1
            texto, monetaria = _cabecalho(v)
            nomes[j] = limpar_texto(str(v))
            for chave, rx in self._re.items():
                if chave in colunas or not rx.search(texto):
                    continue
                if chave == "descricao" and monetaria:
                    continue  # "Lançamentos (R$)" é valor, não histórico
                colunas[chave] = j
                break
            else:
                if monetaria and "valor" not in colunas and re.search(r"LANCAMENTO|VALOR", texto):
                    colunas["valor"] = j
        tem_valor = "valor" in colunas or ("credito" in colunas and "debito" in colunas)
        if "data" in colunas and tem_valor and preenchidas >= self.p.min_colunas_cabecalho:
            return _Mapa(i, colunas, nomes)
        return None

    # --------------------------------------------------------------- leitura
    def processar(self, abas: dict[str, list[list]], res: ResultadoImportacao) -> ResultadoImportacao:
        eventos: list[Evento] = []
        ano_base = self._ano_base(abas)
        mapa: _Mapa | None = None
        idx = 0
        for nome_aba, linhas in abas.items():
            novo = self.achar_cabecalho(linhas)
            if novo:
                mapa, inicio = novo, novo.linha + 1
            elif mapa is not None and linhas:
                inicio = 0  # aba de continuação (PDF convertido em Excel, uma aba por página)
            else:
                continue
            ultimo_mov: Evento | None = None
            data_ant: date | None = None
            for i in range(inicio, len(linhas)):
                linha = linhas[i]
                if not any(v not in (None, "") for v in linha):
                    continue
                if self._mapear(linha, i):  # cabeçalho repetido
                    continue
                num = i + 1
                j_data = mapa.colunas["data"]
                data_linha = self._data(linha[j_data], ano_base, data_ant) if j_data < len(linha) else None
                ev = self._linha(linha, mapa, num, ano_base, data_ant, res)
                if data_linha:
                    data_ant = data_linha  # mesmo linha ignorada define a data das seguintes
                if ev is None:
                    continue
                if ev == "complemento":
                    if ultimo_mov is not None:
                        texto = self._texto_linha(linha)
                        if texto:
                            posicao = ultimo_mov.idx + len(ultimo_mov.complementos) + 1
                            ultimo_mov.complementos.append((posicao, texto))
                    continue
                ev.idx = idx
                idx += 1
                ev.complementos = [(ev.idx + 1, t) for _, t in ev.complementos]
                if nome_aba and len(abas) > 1:
                    ev.linha = num  # linha dentro da aba
                eventos.append(ev)
                if ev.tipo == "mov":
                    ultimo_mov = ev
                    data_ant = ev.data
                elif ev.data:
                    data_ant = ev.data
        motor = MotorTexto(PerfilTexto(sem_sinal=self.p.sem_sinal))
        motor.inferir_sinais(eventos, res)
        motor.montar(eventos, res)
        return res

    def _linha(self, linha: list, mapa: _Mapa, num: int, ano_base: int, data_ant: date | None, res):
        c = mapa.colunas

        def cel(chave: str):
            j = c.get(chave)
            return linha[j] if j is not None and j < len(linha) else None

        descricao = limpar_texto(cel("descricao"))
        complemento = limpar_texto(cel("complemento"))
        tipo_txt = _norm(cel("tipo"))
        data = self._data(cel("data"), ano_base, data_ant)
        texto_norm = _norm(" ".join(x for x in (descricao, str(cel("data") or "")) if x))

        valor_cel, coluna = cel("valor"), None
        if "credito" in c or "debito" in c:
            cred, deb = parse_valor(cel("credito")), parse_valor(cel("debito"))
            if cred not in (None, Decimal("0")):
                valor_cel, coluna = cel("credito"), "C"
            elif deb not in (None, Decimal("0")):
                valor_cel, coluna = cel("debito"), "D"
        texto_valor = str(valor_cel or "").strip()
        bloqueado = texto_valor.startswith("*") or texto_valor.endswith("*")
        valor = parse_valor(texto_valor.strip("*") if bloqueado else valor_cel)
        saldo = parse_valor(cel("saldo"))

        # linha de saldo (SALDO ANTERIOR, SALDO DO DIA...), às vezes sem data
        rotulo = _norm(descricao) or _norm(cel("data"))
        if _SALDO.search(rotulo) or self._ini.search(rotulo):
            valor_saldo = saldo if saldo is not None else valor
            if valor_saldo is None:
                return None
            ev = Evento(0, num, "saldo", data or data_ant, rotulo)  # "SALDO DO DIA" sem data = dia anterior
            ev.saldo = valor_saldo
            ev.inicial = bool(self._ini.search(rotulo))
            ev.saldo_conta = not self._fora.search(rotulo)
            return ev
        if self.p.ignorar and re.search(self.p.ignorar, _norm(descricao)):
            res.ignorados += 1
            return None

        if data is None and valor is not None and descricao and data_ant and not _norm(cel("data")):
            data = data_ant  # data só na primeira linha do dia (Banestes, Bradesco)
        if data is None:
            if valor is None and (descricao or complemento or self._texto_linha(linha)):
                return "complemento"
            if valor is not None and descricao:
                res.erros.append(ErroLinha.de_linha(num, "Data inválida", linha))
            return None
        if valor is None:
            if texto_valor and texto_valor not in ("-", "--"):
                res.erros.append(ErroLinha.de_linha(num, "Valor inválido", linha))
            elif descricao:
                return "complemento"
            return None
        if bloqueado:
            res.ignorados += 1
            res.avisos.append(f"Linha {num}: valor bloqueado ignorado ({descricao[:50]}).")
            return None
        if valor == 0 and not parse_valor(cel("tarifa")):
            res.ignorados += 1
            return None

        sinal = None
        if valor < 0 or texto_valor.upper().rstrip().endswith(("D", "-")):
            sinal = -1
        elif texto_valor.startswith("+") or texto_valor.upper().rstrip().endswith("C"):
            sinal = 1
        if sinal is None and coluna:
            sinal = 1 if coluna == "C" else -1
        if sinal is None and tipo_txt:
            if _DEBITO.search(tipo_txt):
                sinal = -1
            elif _CREDITO.search(tipo_txt):
                sinal = 1
        if sinal is None and self.p.debito_se and re.search(self.p.debito_se, texto_norm + " " + tipo_txt):
            sinal = -1
        elif sinal is None and self.p.credito_se and re.search(self.p.credito_se, texto_norm + " " + tipo_txt):
            sinal = 1

        partes = [descricao]
        if tipo_txt and not (_DEBITO.search(tipo_txt) or _CREDITO.search(tipo_txt)):
            partes.insert(0, limpar_texto(cel("tipo")))
        ev = Evento(0, num, "mov", data, " - ".join(x for x in partes if x), abs(valor), sinal, saldo)
        ev.documento = limpar_texto(cel("documento")).strip("-").strip()
        tarifa = parse_valor(cel("tarifa"))
        if tarifa:
            ev.tarifa = abs(tarifa)
        if complemento:
            ev.complementos.append((ev.idx + 1, complemento))
        usadas = set(c.values())
        for j, nome in mapa.nomes.items():
            if j in usadas or j >= len(linha):
                continue
            v = linha[j]
            if v in (None, "") or _norm(v) in ("DESCONHECIDO", "-", "--"):
                continue
            ev.extras[nome] = limpar_texto(v.strftime("%d/%m/%Y") if isinstance(v, (datetime, date)) else v)
        return ev

    # ----------------------------------------------------------------- datas
    @staticmethod
    def _ano_base(abas: dict[str, list[list]]) -> int:
        for linhas in abas.values():
            for linha in linhas[:40]:
                for v in linha:
                    if isinstance(v, (datetime, date)):
                        return v.year
                    m = re.search(r"\b\d{2}/\d{2}/(\d{4})\b", str(v or ""))
                    if m:
                        return int(m.group(1))
        return date.today().year

    @staticmethod
    def _data(v: object, ano_base: int, anterior: date | None) -> date | None:
        if v in (None, ""):
            return None
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        if isinstance(v, (int, float)) and 20000 < v < 80000:
            return date(1899, 12, 30) + timedelta(days=int(v))  # número serial do Excel
        texto = limpar_texto(v)
        d = parse_data(texto)
        if d:
            return d
        m = re.match(r"^(\d{2})/(\d{2})$", texto)
        if m:
            return MotorTexto.ano_proximo(int(m.group(1)), int(m.group(2)), ano_base, anterior)
        m = re.match(r"^(\d{1,2}) ([A-Za-z]{3})\w* (\d{4})$", sem_acentos(texto))
        if m:
            from extratos_app.services.normalizers import MESES

            mes = MESES.get(m.group(2).lower())
            if mes:
                return date(int(m.group(3)), mes, int(m.group(1)))
        return None

    @staticmethod
    def _texto_linha(linha: list) -> str:
        return limpar_texto(" ".join(str(v) for v in linha if v not in (None, "") and not isinstance(v, (int, float))))
