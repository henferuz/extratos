"""Motor genérico para extratos em texto com colunas (relatórios TXT e PDFs convertidos em texto).

Regras extraídas das amostras reais (BB, Bradesco, Itaú, Santander, CEF, Sicoob, Sicredi,
Banrisul, Inter...):

* uma linha de lançamento tem um valor monetário (e, às vezes, o saldo logo depois);
* o sinal vem explícito (``-``, ``C``/``D``, ``(+)``/``(-)``), pela coluna Crédito/Débito do
  cabeçalho ou, quando o valor vem sem sinal, pela variação do saldo;
* a data aparece na própria linha, numa linha anterior ou como título (``6 de Janeiro de 2023``,
  ``++ MOVIMENTOS NOV/2019``) e vale até aparecer outra;
* o histórico pode estar na linha do valor, acima ou abaixo dela: cada linha de texto sem valor
  é atribuída ao lançamento mais próximo (a distância conta só linhas com texto);
* linhas de saldo (SALDO ANTERIOR, SALDO DO DIA, S A L D O...) não são lançamentos, mas
  alimentam a conferência de saldos.

Cada layout ajusta o comportamento por um `PerfilTexto`.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from extratos_app.models import ENTRADA, SAIDA, Movimento, ResultadoImportacao
from extratos_app.services.normalizers import MESES, limpar_texto, parse_valor, sem_acentos

_NUM = r"\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}"
_NUM_PONTO = r"\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2}"
_SUFIXO = r"(?P<suf>\s?\([+-]\)|\s?[CD](?![A-Za-z0-9])|-(?![\d])|\s-(?=\s|$)|\s?\*)?"


def _regex_valor(num: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<![\w.,/:-])(?P<pre>[-+]\s?)?(?:R\$\s?)?(?P<pre2>[-+]\s?)?"
        rf"(?P<num>{num})(?![\d%])(?!\s?%)" + _SUFIXO
    )


VALOR_BR = _regex_valor(_NUM)
VALOR_PONTO = _regex_valor(_NUM_PONTO)

_DATA_COMPLETA = re.compile(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?![\d/])")
_DATA_DIA_MES = re.compile(r"^\s*(\d{2})/(\d{2})(?![/\d])")
_DATA_MES_TEXTO = re.compile(r"^\s*(\d{2})\s?[/-]\s?([A-Za-z]{3})(?:[/-](\d{2,4}))?\b")
_DATA_EXTENSO = re.compile(r"(\d{1,2})\s+de\s+([A-Za-zçÇ]+)\s+de\s+(\d{4})", re.I)
_PREFIXO_NUMERICO = re.compile(r"^(?:\d+(?:\s?-\s?\d+)?\s+)+(?=\S*[A-Za-z*])")
_TOKEN_DOC = re.compile(r"^(?:\d{3,}|\d{1,3}(?:\.\d{3})+|\d+[-/]\d+)$")

SALDO_PADRAO = r"^(?:\(?[+=-]?\)?\s*)?(S\s?A\s?L\s?D\s?O|SDO\b|SALDO|TOTAL\b)"
SALDO_INICIAL_PADRAO = r"SALDO\s+(ANTERIOR|INICIAL|ANT\b|ANT\.|BLOQ\w*\s+ANTERIOR)|S A L D O A N T E R I O R"
SALDO_FORA_DA_CONTA = r"MEDIO|APLIC|APL\b|BLOQ|LIMITE|INVEST|CDB|POUP|PROVIS|RESUMO|TOTAL\b(?!\s+DISPON)"
IGNORAR_PADRAO = (
    r"^PAG(INA|\.)?\s*:?\s*\d", r"\bPAGINA\s+\d", r"^SAC\b", r"OUVIDORIA", r"^HTTPS?:", r"WWW\.",
    r"^EMITIDO EM", r"^DATA\s*[:/]?\s*(HORA|EMISSAO)?$", r"^LANCAMENTOS$",
    r"^(LANCAMENTOS\s+)?DATA\s+(DE\s+)?(HISTORICO|DESCRICAO|LANCAMENTO|MOV|MOV\.|MOVTO|DOCUMENTO|NR)", r"^FOLHA\s+\d", r"^\d+\s*/\s*\d+$",
)


@dataclass
class PerfilTexto:
    sem_sinal: str = "credito"  # valor sem sinal nem coluna nem saldo: 'credito' ou 'debito'
    usar_colunas: bool = True  # usa posições do cabeçalho Crédito/Débito quando existir
    empate: str = "anterior"  # linha de texto equidistante: 'anterior' ou 'proximo'
    complemento: str = "auto"  # 'auto', 'anterior', 'proximo' ou 'nenhum'
    max_distancia: int = 3
    decimal_ponto: bool = False
    inicio: str | None = None  # regex: só lê depois da primeira linha que casar
    fim: str | None = None  # regex: para de ler (seção seguinte ao extrato)
    ignorar: tuple[str, ...] = ()  # linhas descartadas (cabeçalhos/rodapés/bloqueios)
    ignorar_valor: tuple[str, ...] = ()  # linhas com valor que não são lançamento (sem virar saldo)
    saldo: str = SALDO_PADRAO
    saldo_inicial: str = SALDO_INICIAL_PADRAO
    saldo_fora_da_conta: str = SALDO_FORA_DA_CONTA
    mes_titulo: str | None = None  # ex.: r"MOVIMENTOS\s+(\w{3})/(\d{4})" (Banrisul)
    dia_isolado: bool = False  # linha começando só com o dia ("01  PIX...")
    max_valores_linha: int = 3  # mais que isso: tabela que não é extrato
    ignorar_primeiro_numero: bool = False
    limpar_descricao: str | None = None  # regex removida da descrição (ex.: códigos de sistema)
    credito_se: str | None = None  # valor sem sinal: regex no texto da linha que indica crédito
    debito_se: str | None = None  # idem para débito (ex.: "ENVIADO", "DEBITO")
    saldo_se_sufixo_cd: bool = False  # layouts em que só o saldo leva C/D (valor sozinho com C/D = saldo)
    antes_da_data: str | None = None  # regex no início da linha a ignorar antes da data ("Conciliado")


@dataclass
class Evento:
    idx: int  # índice da linha de texto (para distância)
    linha: int  # número da linha original
    tipo: str  # 'mov' | 'saldo' | 'texto'
    data: date | None = None
    texto: str = ""
    valor: Decimal | None = None
    sinal: int | None = None  # +1, -1 ou None (desconhecido)
    saldo: Decimal | None = None
    saldo_conta: bool = True
    inicial: bool = False
    documento: str = ""
    abre_proximo: bool = False
    so_valor: bool = False  # linha só com o valor (sem data nem texto): célula partida em várias linhas
    tarifa: Decimal = Decimal("0")  # tarifa cobrada à parte do valor (vira uma saída própria)
    extras: dict[str, str] = field(default_factory=dict)  # colunas extras preservadas no Excel
    complementos: list[tuple[int, str]] = field(default_factory=list)


def _familia(texto: str) -> str:
    """Tipo do saldo pelo rótulo, sem datas/números (ex.: 'SDO CTA/APL AUTOMATICAS')."""
    return limpar_texto(re.sub(r"[\d/.,:=>-]+", " ", _n(texto)))[:25] or "saldo"


def _n(texto: str) -> str:
    return sem_acentos(texto).upper()


class MotorTexto:
    def __init__(self, perfil: PerfilTexto) -> None:
        self.p = perfil
        self._re_valor = VALOR_PONTO if perfil.decimal_ponto else VALOR_BR
        self._ignorar = [re.compile(x) for x in (*IGNORAR_PADRAO, *perfil.ignorar)]
        self._ignorar_valor = [re.compile(x) for x in perfil.ignorar_valor]

    # ------------------------------------------------------------------ datas
    def _ano_base(self, linhas: list[str]) -> int:
        anos = Counter()
        for l in linhas:
            for m in re.finditer(r"\b\d{1,2}[/.-]\d{1,2}[/.-](\d{4})\b", l):
                anos[int(m.group(1))] += 1
            for m in _DATA_EXTENSO.finditer(l):
                anos[int(m.group(3))] += 1
        return anos.most_common(1)[0][0] if anos else date.today().year

    @staticmethod
    def ano_proximo(dia: int, mes: int, ano_base: int, anterior: date | None) -> date | None:
        referencia = anterior or date(ano_base, mes, 1)
        candidatos = []
        for ano in (referencia.year - 1, referencia.year, referencia.year + 1):
            try:
                candidatos.append(date(ano, mes, dia))
            except ValueError:
                continue
        if not candidatos:
            return None
        return min(candidatos, key=lambda d: abs((d - referencia).days))

    def _coluna_data(self, linhas: list[str]) -> int:
        cols = Counter()
        for l in linhas:
            m = _DATA_COMPLETA.match(l) or _DATA_DIA_MES.match(l)
            if m and self._re_valor.search(l):
                cols[len(l) - len(l.lstrip())] += 1
        return cols.most_common(1)[0][0] if cols else 0

    def _extrair_data(self, linha: str, ano_base: int, anterior: date | None, col_data: int):
        """Retorna (data, span) se a linha começa com data na coluna esperada.

        Linhas de texto sem valor muito recuadas (ex.: complemento "01/12 1916 FULANO" do BB)
        não mudam a data; linhas com valor aceitam a data como primeiro campo em qualquer recuo."""
        indent = len(linha) - len(linha.lstrip())
        if indent > col_data + 8 and not self._re_valor.search(linha):
            m = _DATA_EXTENSO.search(linha)
            return self._data_extenso(m) if m else (None, None)
        m = _DATA_COMPLETA.match(linha)
        if m:
            d, mth, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
            a = a + 2000 if a < 100 else a
            try:
                return date(a, mth, d), m.span()
            except ValueError:
                return None, None
        m = _DATA_MES_TEXTO.match(linha)
        if m and m.group(2).lower()[:3] in MESES:
            mes = MESES[m.group(2).lower()[:3]]
            if m.group(3):
                a = int(m.group(3))
                a = a + 2000 if a < 100 else a
                try:
                    return date(a, mes, int(m.group(1))), m.span()
                except ValueError:
                    return None, None
            return self.ano_proximo(int(m.group(1)), mes, ano_base, anterior), m.span()
        m = _DATA_DIA_MES.match(linha)
        if m and 1 <= int(m.group(1)) <= 31 and 1 <= int(m.group(2)) <= 12:
            return self.ano_proximo(int(m.group(1)), int(m.group(2)), ano_base, anterior), m.span()
        m = _DATA_EXTENSO.search(linha)
        if m:
            return self._data_extenso(m)
        return None, None

    @staticmethod
    def _data_extenso(m: re.Match[str]):
        mes = MESES.get(sem_acentos(m.group(2)).lower()[:3])
        if not mes:
            return None, None
        try:
            return date(int(m.group(3)), mes, int(m.group(1))), m.span()
        except ValueError:
            return None, None

    # --------------------------------------------------------------- colunas
    @staticmethod
    def _cabecalho_colunas(linha_norm: str) -> dict[str, float] | None:
        # posição = início do título; o valor pertence à última coluna que começa antes do fim dele
        cred = re.search(r"\b(CREDITOS?|ENTRADAS?)\b", linha_norm)
        deb = re.search(r"\b(DEBITOS?|SAIDAS?)\b", linha_norm)
        if not (cred and deb):
            # tabela "Valor | Saldo": só serve para reconhecer saldo sozinho na coluna Saldo
            val = re.search(r"\bVALOR\b", linha_norm)
            sal = re.search(r"\bSALDO\b", linha_norm)
            if val and sal and sal.start() > val.end() and re.search(r"\b(DATA|HISTORICO|DESCRICAO)\b", linha_norm):
                return {"V": val.start(), "S": sal.start() + 2}
            return None
        # só é cabeçalho de tabela se tiver outra coluna típica (evita "(créditos) (débitos)")
        if not re.search(r"\b(DATA|HISTORICO|DESCRICAO|LANCAMENTOS?|SALDO|DOCUMENTO|DCTO|DOCTO)\b", linha_norm):
            return None
        cols = {"C": cred.start(), "D": deb.start()}
        sal = re.search(r"\bSALDO\b", linha_norm)
        if sal and sal.start() > max(cols.values()):
            cols["S"] = sal.start()
        return cols

    # ------------------------------------------------------------------ motor
    def processar(self, linhas: list[str], resultado: ResultadoImportacao) -> ResultadoImportacao:
        p = self.p
        ano_base = self._ano_base(linhas)
        col_data = self._coluna_data(linhas)
        re_inicio = re.compile(p.inicio) if p.inicio else None
        re_fim = re.compile(p.fim) if p.fim else None
        re_saldo, re_ini = re.compile(p.saldo), re.compile(p.saldo_inicial)
        re_fora = re.compile(p.saldo_fora_da_conta)
        re_mes = re.compile(p.mes_titulo) if p.mes_titulo else None

        # ícones de fonte (uso privado) viram espaço, preservando as colunas
        linhas = ["".join(" " if unicodedata.category(c) == "Co" else c for c in l) for l in linhas]
        linhas = self._juntar_sinais_orfaos(linhas)
        eventos: list[Evento] = []
        data_atual: date | None = None
        colunas: dict[str, float] | None = None
        ativo = re_inicio is None
        idx_texto = 0
        mes_ctx: tuple[int, int] | None = None

        for num, bruta in enumerate(linhas, start=1):
            if not bruta.strip():
                continue
            norm = _n(bruta)
            norm_limpo = limpar_texto(norm)
            if not ativo:
                if re_inicio.search(norm_limpo):
                    ativo = True
                    cab = self._cabecalho_colunas(norm)
                    if cab:
                        colunas = cab
                continue
            if re_fim and re_fim.search(norm_limpo):
                break
            cab = self._cabecalho_colunas(norm)
            if cab and not self._re_valor.search(bruta):
                colunas = cab if p.usar_colunas else None
                continue
            if any(r.search(norm_limpo) for r in self._ignorar):
                continue
            if re_mes:
                m = re_mes.search(norm_limpo)
                if m:
                    mes_ctx = (MESES.get(m.group(1).lower()[:3], 0), int(m.group(2)))
                    continue

            linha = bruta
            if p.antes_da_data:
                linha = re.sub(p.antes_da_data, lambda m: " " * len(m.group(0)), linha, count=1)
            # ---- data
            data, span = None, None
            if p.dia_isolado and mes_ctx and mes_ctx[0]:
                m = re.match(r"^\s{0,6}(\d{2})\s{1,}(?=\S)", linha)
                if m and 1 <= int(m.group(1)) <= 31 and not _DATA_DIA_MES.match(linha):
                    try:
                        data, span = date(mes_ctx[1], mes_ctx[0], int(m.group(1))), m.span()
                    except ValueError:
                        pass
            if data is None:
                data, span = self._extrair_data(linha, ano_base, data_atual, col_data)
            if data:
                data_atual = data
                linha = linha[: span[0]] + " " * (span[1] - span[0]) + linha[span[1]:]

            # ---- valores
            valores = list(self._re_valor.finditer(linha))
            if len(valores) > p.max_valores_linha:
                continue
            texto_sem_valor = linha
            for m in reversed(valores):
                texto_sem_valor = texto_sem_valor[: m.start()] + " " * (m.end() - m.start()) + texto_sem_valor[m.end():]
            texto = limpar_texto(texto_sem_valor)
            # códigos numéricos no início (agência/lote/histórico) não fazem parte da descrição
            prefixo = _PREFIXO_NUMERICO.match(texto)
            codigos = prefixo.group(0).split() if prefixo else []
            texto = texto[prefixo.end():] if prefixo else texto
            texto_norm = _n(texto)

            if not valores:
                anterior = eventos[-1] if eventos else None
                if (
                    anterior is not None and anterior.tipo == "mov" and anterior.so_valor
                    and anterior.idx == idx_texto - 1 and re_saldo.search(texto_norm)
                ):
                    # valor impresso na linha de cima do rótulo "SALDO DO DIA": é saldo, não lançamento
                    anterior.tipo, anterior.texto = "saldo", texto
                    anterior.saldo = anterior.valor * (anterior.sinal or 1)
                    anterior.inicial = bool(re_ini.search(texto_norm))
                    anterior.saldo_conta = not re_fora.search(texto_norm)
                    continue
                if texto and "*" not in texto_norm[-1:]:
                    ev = Evento(idx_texto, num, "texto", data_atual, texto)
                    ev.abre_proximo = data is not None  # "01/07/2024 Pagamento de Boleto" → próximo valor
                    eventos.append(ev)
                    idx_texto += 1
                continue

            if valores and any(r.search(norm_limpo) for r in self._ignorar_valor):
                resultado.ignorados += 1
                continue

            # saldo?
            if re_saldo.search(texto_norm) or re_ini.search(texto_norm):
                ev = Evento(idx_texto, num, "saldo", data_atual, texto)
                ev.saldo = self._numero(valores[-1])
                ev.inicial = bool(re_ini.search(texto_norm))
                ev.saldo_conta = not re_fora.search(texto_norm)
                eventos.append(ev)
                idx_texto += 1
                continue

            # ---- lançamento
            if p.saldo_se_sufixo_cd and len(valores) == 1 and (valores[0].group("suf") or "").strip() in ("C", "D"):
                ev = Evento(idx_texto, num, "saldo", data_atual, texto)
                ev.saldo = self._numero(valores[0])
                eventos.append(ev)
                idx_texto += 1
                continue
            mov, saldo = valores[0], None
            coluna = None
            if colunas and "V" in colunas:
                # PDF não tem largura fixa: só confia na posição quando a linha não tem descrição
                if len(valores) == 1 and not texto and self._coluna_de(valores[0], colunas) == "S":
                    ev = Evento(idx_texto, num, "saldo", data_atual, texto)
                    ev.saldo = self._numero(valores[0])
                    eventos.append(ev)
                    idx_texto += 1
                    continue
                if len(valores) >= 2:
                    saldo = self._numero(valores[-1])
            elif colunas and len(valores) >= 1:
                classes = [self._coluna_de(v, colunas) for v in valores]
                movs = [v for v, c in zip(valores, classes) if c in ("C", "D")]
                saldos = [v for v, c in zip(valores, classes) if c == "S"]
                if not movs:
                    # só saldo na linha (ex.: Bradesco "SALDO" ao fim do dia sem rótulo)
                    ev = Evento(idx_texto, num, "saldo", data_atual, texto)
                    ev.saldo = self._numero(saldos[-1])
                    eventos.append(ev)
                    idx_texto += 1
                    continue
                mov = movs[0]
                saldo = self._numero(saldos[-1]) if saldos else None
                coluna = classes[valores.index(mov)]
            elif len(valores) >= 2:
                saldo = self._numero(valores[-1])

            if (mov.group("suf") or "").strip() == "*":
                resultado.ignorados += 1
                resultado.avisos.append(f"Linha {num}: depósito bloqueado ignorado ({limpar_texto(bruta)[:60]}).")
                continue
            if data_atual is None:
                continue  # valores antes da primeira data são o resumo do cabeçalho

            valor = self._numero(mov)
            sinal = self._sinal_explicito(mov)
            if sinal is None and coluna in ("C", "D"):
                sinal = 1 if coluna == "C" else -1
            if sinal is None and p.debito_se and re.search(p.debito_se, norm_limpo):
                sinal = -1
            elif sinal is None and p.credito_se and re.search(p.credito_se, norm_limpo):
                sinal = 1
            documento = ""
            if p.limpar_descricao:
                texto = limpar_texto(re.sub(p.limpar_descricao, " ", texto))
            partes = texto.split(" ")
            if len(partes) > 1 and _TOKEN_DOC.match(partes[-1]):
                documento = partes.pop()
                texto = " ".join(partes)
            if p.ignorar_primeiro_numero and len(partes) > 1 and _TOKEN_DOC.match(partes[0]):
                texto = " ".join(partes[1:])
            if texto and all(re.fullmatch(r"[\d./-]+", t) for t in texto.split()):
                codigos += texto.split()  # só números (lote/documento): não é descrição
                texto = ""
            if not documento and codigos:
                documento = max(codigos, key=len) if len(max(codigos, key=len)) >= 5 else ""
            ev = Evento(idx_texto, num, "mov", data_atual, texto, abs(valor), sinal, saldo, documento=documento)
            ev.so_valor = data is None and not texto
            eventos.append(ev)
            idx_texto += 1

        self._atribuir_textos(eventos)
        self.inferir_sinais(eventos, resultado)
        self.montar(eventos, resultado)
        return resultado

    # ------------------------------------------------------------- auxiliares
    def _juntar_sinais_orfaos(self, linhas: list[str]) -> list[str]:
        """Célula do PDF partida em várias linhas: um 'C'/'D' sozinho na linha, ou um '-'/'+'
        isolado no fim da linha, pertence ao valor sem sinal da mesma coluna numa linha vizinha
        (até 2 linhas de distância)."""
        linhas = list(linhas)
        for i, linha in enumerate(linhas):
            simbolo = linha.strip()
            if simbolo in ("C", "D", "-", "+"):
                col = len(linha) - len(linha.lstrip())
                inicio = 0
            else:
                m_sinal = re.search(r"(?<=\S\s{3})[-+](?=\s*$)", linha)
                if not m_sinal or self._re_valor.search(linha):
                    continue
                simbolo, col, inicio = m_sinal.group(0), m_sinal.start(), m_sinal.start()
            juntou = False
            for j in (i - 1, i + 1, i - 2, i + 2):
                if juntou or not 0 <= j < len(linhas):
                    continue
                for m in self._re_valor.finditer(linhas[j]):
                    if self._sinal_explicito(m) is not None:
                        continue
                    if simbolo in ("C", "D") and abs(m.end() - col) <= 4:
                        linhas[j] = linhas[j][: m.end()] + " " + simbolo + linhas[j][m.end():]
                    elif simbolo in ("-", "+") and abs(m.start() - col) <= 6:
                        linhas[j] = linhas[j][: m.start()] + simbolo + linhas[j][m.start():]
                    else:
                        continue
                    linhas[i] = linhas[i][:inicio].rstrip() if inicio else ""
                    juntou = True
                    break
        return linhas

    def _numero(self, m: re.Match[str]) -> Decimal:
        num = m.group("num")
        if self.p.decimal_ponto:
            num = num.replace(",", "").replace(".", ",")
        valor = parse_valor(num)
        sinal = self._sinal_explicito(m)
        return -valor if sinal == -1 else valor

    @staticmethod
    def _sinal_explicito(m: re.Match[str]) -> int | None:
        pre = ((m.group("pre") or "") + (m.group("pre2") or "")).strip()
        suf = (m.group("suf") or "").strip()
        if "-" in pre or suf in ("D", "-", "(-)"):
            return -1
        if "+" in pre or suf in ("C", "(+)"):
            return 1
        return None

    @staticmethod
    def _coluna_de(m: re.Match[str], colunas: dict[str, float]) -> str:
        fim = m.end("num")
        ordem = sorted(colunas, key=colunas.get)
        escolhida = ordem[0]
        for k in ordem:
            if colunas[k] < fim:
                escolhida = k
        return escolhida

    def _atribuir_textos(self, eventos: list[Evento]) -> None:
        """Cada linha de texto vai para o lançamento mais próximo (sem atravessar linhas de saldo)."""
        modo = self.p.complemento
        if modo == "nenhum":
            return
        ancoras = [i for i, e in enumerate(eventos) if e.tipo in ("mov", "saldo")]
        for i, ev in enumerate(eventos):
            if ev.tipo != "texto":
                continue
            ant = next((j for j in reversed(ancoras) if j < i), None)
            prox = next((j for j in ancoras if j > i), None)
            cand_ant = eventos[ant] if ant is not None and eventos[ant].tipo == "mov" else None
            cand_prox = eventos[prox] if prox is not None and eventos[prox].tipo == "mov" else None
            if modo == "anterior":
                cand_prox = None
            elif modo == "proximo":
                cand_ant = None
            d_ant = ev.idx - cand_ant.idx if cand_ant else 10**6
            d_prox = cand_prox.idx - ev.idx if cand_prox else 10**6
            if min(d_ant, d_prox) > self.p.max_distancia:
                continue
            if ev.abre_proximo and cand_ant is not None and cand_ant.so_valor and d_ant == 1 and not cand_ant.complementos:
                alvo = cand_ant  # valor impresso uma linha acima da data/histórico
                alvo.data = ev.data
            elif ev.abre_proximo and cand_prox is not None and d_prox <= self.p.max_distancia:
                alvo = cand_prox
            elif d_ant < d_prox or (d_ant == d_prox and self.p.empate == "anterior"):
                alvo = cand_ant
            else:
                alvo = cand_prox
            if alvo is not None:
                alvo.complementos.append((ev.idx, ev.texto))

    def inferir_sinais(self, eventos: list[Evento], res: ResultadoImportacao) -> None:
        """Testa as ordens cronológicas possíveis e fica com a que melhor bate com os saldos.

        Extratos em ordem decrescente podem estar invertidos por inteiro ou só por dia (dias do
        mais recente para o mais antigo, lançamentos do dia em ordem crescente)."""
        base = [e for e in eventos if e.tipo in ("mov", "saldo")]
        candidatas = [base, list(reversed(base))]
        blocos: list[list[Evento]] = []
        for e in base:
            if blocos and blocos[-1][0].data == e.data:
                blocos[-1].append(e)
            else:
                blocos.append([e])
        candidatas.append([e for bloco in reversed(blocos) for e in bloco])
        # "Saldo do dia" impresso no topo do dia, mas é o saldo depois dos lançamentos do dia
        fim_do_dia = [
            [e for e in b if e.inicial] + [e for e in b if e.tipo == "mov"] + [e for e in b if e.tipo == "saldo" and not e.inicial]
            for b in blocos
        ]
        candidatas.append([e for bloco in fim_do_dia for e in bloco])
        candidatas.append([e for bloco in reversed(fim_do_dia) for e in bloco])
        sinais = [e.sinal for e in base]
        melhor = None
        for ordem in candidatas:
            for e, sinal in zip(base, sinais):
                e.sinal = sinal
            teste = ResultadoImportacao(res.arquivo)
            self._simular(ordem, teste)
            certos = sum(c for c, _ in teste.trechos.values())
            if melhor is None or certos > melhor[0]:
                melhor = (certos, ordem)
        for e, sinal in zip(base, sinais):
            e.sinal = sinal
        self._simular(melhor[1], res)

    def _simular(self, ordem: list[Evento], res: ResultadoImportacao) -> None:
        """Define o sinal dos valores sem sinal pela variação do saldo e registra as observações de
        saldo para a conferência por trechos (cada par de saldos consecutivos do mesmo tipo)."""
        corrente: Decimal | None = None
        saldo_inicial: Decimal | None = next(
            (e.saldo for e in ordem if e.tipo == "saldo" and e.inicial and e.saldo is not None),
            None,
        )
        ultimo: Decimal | None = None
        acumulado = Decimal("0")
        observacoes: dict[str, list[tuple[Decimal, Decimal, int]]] = defaultdict(list)
        for e in ordem:
            if e.tipo == "saldo":
                familia = "conta" if e.saldo_conta else _familia(e.texto)
                observacoes[familia].append((acumulado, e.saldo, e.linha))
                if e.saldo_conta and not e.inicial:
                    # a mesma conta pode ter séries diferentes (ex.: "saldo total" x "saldo movimentação")
                    observacoes["rotulo:" + _familia(e.texto)].append((acumulado, e.saldo, e.linha))
                if not e.saldo_conta:
                    continue
                corrente = ultimo = e.saldo
                continue
            if e.sinal is None and e.saldo is not None and corrente is not None:
                if corrente + e.valor == e.saldo:
                    e.sinal = 1
                elif corrente - e.valor == e.saldo:
                    e.sinal = -1
            if e.sinal is None:
                e.sinal = -1 if self.p.sem_sinal == "debito" else 1
            acumulado += e.sinal * e.valor - e.tarifa
            if e.saldo is not None:
                if corrente is None and saldo_inicial is None:
                    saldo_inicial = e.saldo - e.sinal * e.valor + e.tarifa
                    observacoes["conta"].append((acumulado - e.sinal * e.valor + e.tarifa, saldo_inicial, e.linha))
                observacoes["conta"].append((acumulado, e.saldo, e.linha))
                corrente = e.saldo
            elif corrente is not None:
                corrente = corrente + e.sinal * e.valor - e.tarifa
            ultimo = corrente
        res.saldo_inicial = saldo_inicial
        res.saldo_final = ultimo
        for familia, obs in observacoes.items():
            pares = list(zip(obs, obs[1:]))
            falhos = [(l1, l2) for (a1, s1, l1), (a2, s2, l2) in pares if abs((s2 - s1) - (a2 - a1)) > Decimal("0.05")]
            if pares:
                res.trechos[familia] = (len(pares) - len(falhos), len(pares))
                res.trechos_falhos[familia] = falhos

    @staticmethod
    def montar(eventos: list[Evento], res: ResultadoImportacao) -> None:
        for e in eventos:
            if e.tipo != "mov":
                continue
            antes = [t for i, t in sorted(e.complementos) if i < e.idx]
            depois = [t for i, t in sorted(e.complementos) if i > e.idx]
            descricao = " ".join(x for x in (*antes, e.texto) if x).strip()
            complemento = " ".join(depois).strip()
            if not descricao:
                descricao, complemento = complemento, ""
            mov = Movimento(
                data=e.data,
                descricao=descricao or "(sem descrição)",
                valor=e.valor,
                tipo=ENTRADA if e.sinal and e.sinal > 0 else SAIDA,
                documento=e.documento,
                linha_origem=e.linha,
            )
            if complemento:
                mov.extras["Complemento"] = complemento
            mov.extras.update(e.extras)
            res.movimentos.append(mov)
            if e.tarifa:
                res.movimentos.append(
                    Movimento(
                        data=e.data,
                        descricao=f"Tarifa - {mov.descricao}",
                        valor=e.tarifa,
                        tipo=SAIDA,
                        documento=e.documento,
                        historico="TARIFA",
                        linha_origem=e.linha,
                    )
                )
