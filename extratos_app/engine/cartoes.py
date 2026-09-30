"""Motor de normalização de vendas e recebimentos de cartões."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from extratos_app.models import ENTRADA, SAIDA, ErroLinha, Movimento, ResultadoImportacao
from extratos_app.services.normalizers import limpar_texto, parse_data, parse_valor, sem_acentos


def _norm(value: object) -> str:
    return " ".join(sem_acentos(str(value or "")).upper().split())


def _header_norm(value: object) -> str:
    """Normaliza separadores de cabeçalhos sem alterar o texto exibido."""
    texto = sem_acentos(str(value or "")).upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", texto).split())


def _cabecalho_em_duas_linhas(linhas: list[list], numero: int) -> list:
    """Junta a linha seguinte quando o cabeçalho repete rótulos e continua abaixo.

    Ex.: extrato Ticket, com ``Data | Data`` completados por ``Corte | Transação``.
    Só junta quando a continuação é texto (sem data nem valor) sob células preenchidas.
    """
    linha = linhas[numero]
    rotulos = [_header_norm(valor) for valor in linha if _header_norm(valor)]
    if len(rotulos) == len(set(rotulos)) or numero + 1 >= len(linhas):
        return linha
    seguinte = linhas[numero + 1]
    preenchidas = [indice for indice, valor in enumerate(seguinte) if limpar_texto(valor)]
    if len(preenchidas) < 2 or any(
        indice >= len(linha)
        or not limpar_texto(linha[indice])
        or parse_data(seguinte[indice]) is not None
        or parse_valor(seguinte[indice]) is not None
        for indice in preenchidas
    ):
        return linha
    return [
        f"{limpar_texto(valor)} {limpar_texto(seguinte[indice]) if indice < len(seguinte) else ''}".strip()
        for indice, valor in enumerate(linha)
    ]


@dataclass
class PerfilCartao:
    grupo: str = "A"
    colunas: dict[str, tuple[str, ...]] = field(default_factory=lambda: {
        "data_venda": (
            "DATA VENDA", "DATA DA VENDA", "EMISSAO", "DT VENDA", "DATATRANSACAO",
            "D. LANCAMENTO", "D. MOVIMENTO", "DT.MOVIMENTO", "DATA DA OPERACAO", "DATA DE CRIACAO",
            "DATA/HORA DA VENDA", "DATA DA TRANSACAO", "DATA LANCAMENTO", "DATA OPERACAO",
            "DATA CRIACAO", "CREATION DATE", "TRANSACTION DATE", "TRANSACTION DATE PAYMENT",
            "DATE E HORA DA VENDA", "DATE CREATED", "DATA DO MOVIMENTO", "FECHA DE COMPRA",
            "DT PREV LIQUID", "DATA DE CONCLUSAO",
            "DATA DE VENDA", "DATA DEVENDA", "DATA TRANSACAO", "DATA HORA", "DATA E HORA",
            "DATA INICIAL", "DATA E HORA DO PEDIDO", "DATA DO PEDIDO",
        ),
        "data_pagamento": (
            "DATA PAGAMENTO", "RECEBIMENTO", "DATA DE PAGAMENTO", "DATAPREVISTAPAGTO",
            "D. LIQUIDACAO", "DATA REPASSE", "PREVISAO DE PAGAMENTO", "DATA PREVISTA DO PAGAMENTO",
            "DATA PREVISTA DO 1 PAGAMENTO", "DATA DE CREDITO", "UPDATE DATE", "VENCIMENTO",
            "DATA DE LIQUIDACAO", "DATA PREV CREDITO", "DATA DE LIBERACAO", "DATA DE ORIGEM",
            "DATA CRED DEB", "DATA CRE DEB",
        ),
        "bruto": (
            "BRUTO", "VALOR BRUTO", "VLR BRUTO", "VALOR DA VENDA", "VLR.VDA", "VLR VENDA",
            "VALORBRUTOPARCELA", "V. ORIGINAL", "VL.BRUTO", "VALOR ORIGINAL", "ENTRADA BRUTA",
            "QUANTIA TOTAL LANCADA", "VALOR CREDITO", "VALOR CREDITO A VISTA", "VALOR A VISTA",
            "VALOR COMPRA", "VALOR PARCELA", "VALOR DOS ITENS", "VALOR TRANSACAO",
            "VALOR DA OPERACAO", "VALOR DA TARIFA", "TRANSACTION AMOUNT", "PRECO ORIGINAL", "PRICE ORIGINAL",
            "VALOR DEL PRODUCTO", "VALOR BRUTO DAS VENDAS", "VALOR BRUTO DA OPERACAO",
            "VALOR DO COMPRA",
        ),
        "taxa": (
            "TAXA", "MDR", "DESCONTO", "TARIFA", "COMISSAO", "TX. ADM", "TX ADM", "VALORDESCONTOPARCELA",
            "VL.COMISSAO", "VALOR DA TAXA", "TAXA TOTAL", "TAXA DE OPERACAO", "TAXA DE COMISSAO", "DESCONTOS",
            "VALOR TX ADM", "VALOR TX ADM MDR", "FEE", "TAX", "FEE AMOUNT", "TARIFA DE MERCADO PAGO",
            "TARIFA ADMINISTRACAO", "TARIFAS E COMISSOES", "VALOR DESCONTADO", "TAXAS",
        ),
        # Somado à taxa: a antecipação também sai do bruto (Stone).
        "taxa_antecipacao": ("DESCONTO DE ANTECIPACAO",),
        "taxa_percentual": ("TAXA PERCENTUAL", "TAXA %", "PERCENTUAL", "PERCENT", "ALIQUOTA"),
        "liquido": (
            "LIQUIDO", "VALOR LIQUIDO", "VLR LIQUIDO", "VLR.LIQ", "VALOR RECEBIDO", "PAGO",
            "VALORLIQUIDOPARCELA", "V. RECEBIMENTO", "VL.LIQUIDO", "ENTRADA LIQUIDA", "A RECEBER",
            "VALOR DE PAGAMENTO", "PRICE SELLER", "AMOUNT RECEIVED", "SETTLEMENT NET AMOUNT",
        ),
        "status": ("STATUS", "SITUACAO", "TIPO", "MOVIMENTO", "TIPO DE OPERACAO", "TIPO DE LANCAMENTO", "STATUS DO PEDIDO", "OUR STATUS"),
        "nsu": ("NSU", "ID TRANSACAO", "TRANSACAO", "NRO TRANSACAO", "ID GRANITO", "NUMERO DOCTO"),
        "autorizacao": ("AUTORIZACAO", "COD AUT", "AUT"),
        "bandeira": ("BANDEIRA", "BRAND"),
        "parcela": ("PARCELA", "N PARCELA", "NUMERO PARCELA"),
        "operacao": ("OPERACAO", "TIPO DE TRANSACAO", "FORMA DE PAGAMENTO", "MODALIDADE"),
        "produto": ("PRODUTO", "TIPO PRODUTO", "MEIO DE PAGAMENTO"),
        # Extratos de reembolso (Ticket, Policard): histórico da linha e débitos em coluna própria.
        "descricao": ("DESCRICAO LANCAMENTO", "TIPO LANCAMENTO"),
        "debito": ("VALOR DEBITO", "SAIDA BRUTA"),
    })


class MotorCartoes:
    def __init__(self, perfil: PerfilCartao) -> None:
        self.p = perfil

    def _mapear(self, linhas: list[list]) -> tuple[int, dict[str, int], dict[int, str]] | None:
        # A busca de cabeçalho segue o mesmo limite/contrato do MotorPlanilha.
        # O cabeçalho genérico pode reconhecer um resumo anterior ao quadro
        # de vendas (por exemplo, ``Valor Bruto`` no total do relatório).
        # Cartões têm semântica própria, então a busca precisa começar no
        # início da aba e escolher a primeira linha com colunas de tabela.
        inicio = 0
        for numero in range(inicio, min(len(linhas), inicio + 80)):
            linha = _cabecalho_em_duas_linhas(linhas, numero)
            indices: dict[str, int] = {}
            nomes: dict[int, str] = {}
            candidatos: list[tuple[int, int, int, int, str]] = []
            for indice, valor in enumerate(linha):
                nome = limpar_texto(str(valor or ""))
                normalizado = _header_norm(nome)
                if not normalizado:
                    continue
                nomes[indice] = nome
                if "%" in nome or re.search(r"\b(?:PERCENT|PERCENTUAL|ALIQUOTA)\b", normalizado):
                    candidatos.append((0, 99, indice, list(self.p.colunas).index("taxa_percentual"), "taxa_percentual"))
                    continue
                for ordem, (campo, sinonimos) in enumerate(self.p.colunas.items()):
                    if campo == "taxa_percentual":
                        continue
                    if campo == "taxa" and re.search(r"\b(?:MINIM[AO]|EMBARQUE)\b|^TAXA DE ANTECIPACAO$", normalizado):
                        # "Comissão mínima", "Taxa de embarque" e a "Taxa de antecipação" da Cielo
                        # (taxa contratada) não são o valor descontado da venda.
                        continue
                    for sinonimo in sinonimos:
                        chave = _header_norm(sinonimo)
                        palavras = chave.split()
                        if normalizado == chave or normalizado.replace(" ", "") == chave.replace(" ", ""):
                            candidatos.append((0, -len(palavras), indice, ordem, campo))
                        elif len(palavras) == 1 and chave in {"AUT", "TAX", "TIPO", "PAGO"}:
                            continue
                        elif all(re.search(rf"\b{re.escape(palavra)}\b", normalizado) for palavra in palavras):
                            candidatos.append((1, -len(palavras), indice, ordem, campo))
                        elif chave.startswith(("VLR ", "VL ")) and chave in normalizado:
                            candidatos.append((2, -len(palavras), indice, ordem, campo))
            cabecalhos_usados: set[int] = set()
            for _, _, indice, _, campo in sorted(candidatos):
                if indice not in cabecalhos_usados and campo not in indices:
                    indices[campo] = indice
                    cabecalhos_usados.add(indice)
            # "Tipo" (Débito/Crédito) só serve de status se não houver coluna de status de verdade.
            colunas_status = [
                indice for indice, nome in nomes.items()
                if re.search(r"\bSTATUS\b", _header_norm(nome)) and not re.match(r"(DATA|HORA)\b", _header_norm(nome))
            ]
            if colunas_status and indices.get("status") not in colunas_status and colunas_status[0] not in indices.values():
                indices["status"] = colunas_status[0]
            if "data_venda" not in indices:
                for indice, nome in nomes.items():
                    if _header_norm(nome) in {"HORA DA VENDA", "VENDA"}:
                        indices["data_venda"] = indice
                        break
            if "data_venda" not in indices:
                datas_genericas = [indice for indice, nome in nomes.items() if _header_norm(nome) == "DATA"]
                if datas_genericas:
                    indices["data_venda"] = datas_genericas[0]
            # Relatórios tabulares usam nomes curtos sem a semântica de
            # adquirente. Esses rótulos só são aceitos depois que a detecção
            # já classificou o arquivo como cartão.
            canonicos = {_header_norm(nome): indice for indice, nome in nomes.items()}
            if "bruto" not in indices:
                for rotulo in (
                    "VALOR", "TOTAL", "AMOUNT", "DEDUCTED AMOUNT", "HOMOLOGADO", "VALOR TOTAL",
                    "ENTRADA", "VALOR R$",
                ):
                    if _header_norm(rotulo) in canonicos:
                        indices["bruto"] = canonicos[_header_norm(rotulo)]
                        break
            if "liquido" not in indices:
                for rotulo in ("AMOUNT RECEIVED", "VALOR RECEBIDO", "PRICE SELLER", "SETTLEMENT NET AMOUNT"):
                    if _header_norm(rotulo) in canonicos:
                        indices["liquido"] = canonicos[_header_norm(rotulo)]
                        break
            if "taxa" not in indices:
                for rotulo in ("FEE", "TAX", "VALOR TX ADM", "FEE AMOUNT", "TARIFA DE MERCADO PAGO"):
                    if _header_norm(rotulo) in canonicos:
                        indices["taxa"] = canonicos[_header_norm(rotulo)]
                        break
            if "data_venda" not in indices and "DETALHAMENTO" in _norm(linha[0] if linha else ""):
                continue
            if "liquido" not in indices and self.p.grupo == "B":
                for rotulo in ("VALOR DA TARIFA", "TARIFA DE MERCADO PAGO"):
                    if _header_norm(rotulo) in canonicos:
                        indices["liquido"] = canonicos[_header_norm(rotulo)]
                        break
            if "TOTAL" in canonicos and "bruto" in indices:
                bruto_nome = _header_norm(nomes[indices["bruto"]])
                if bruto_nome.startswith("VALOR ") and bruto_nome != "VALOR BRUTO":
                    indices["bruto"] = canonicos["TOTAL"]
            if ("data_venda" in indices or "data_pagamento" in indices) and ("bruto" in indices or "liquido" in indices):
                return numero, indices, nomes
        return None

    @staticmethod
    def _valor(linha: list, indices: dict[str, int], campo: str) -> Decimal | None:
        indice = indices.get(campo)
        if indice is None or indice >= len(linha):
            return None
        valor = linha[indice]
        if isinstance(valor, str):
            if "R$" not in valor.upper():
                valor = valor.replace("US$", "").replace("$", "")
        return parse_valor(valor)

    @staticmethod
    def _data(valor: object) -> date | None:
        data = parse_data(valor)
        if data is not None:
            return data
        texto = limpar_texto(valor)
        # Exportações do TON/Yapay usam ``d/m/aaaa, hh:mm``.
        texto = re.sub(r",\s*\d{1,2}:\d{2}(?::\d{2})?$", "", texto)
        parcial = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
        if parcial:
            try:
                return date(int(parcial.group(3)), int(parcial.group(2)), int(parcial.group(1)))
            except ValueError:
                return None
        if texto.isdigit():
            serial = int(texto)
            if 20_000 < serial < 80_000:
                return date(1899, 12, 30) + timedelta(days=serial)
        try:
            serial = float(texto.replace(",", "."))
        except ValueError:
            serial = 0
        if 20_000 < serial < 80_000:
            return date(1899, 12, 30) + timedelta(days=serial)
        return None

    @staticmethod
    def _texto(linha: list, indices: dict[str, int], campo: str) -> str:
        indice = indices.get(campo)
        return limpar_texto(linha[indice]) if indice is not None and indice < len(linha) else ""

    def processar(self, abas: dict[str, list[list]], resultado: ResultadoImportacao) -> ResultadoImportacao:
        conferidos = 0
        divergentes = 0
        encontrou_liquido = False
        avisou_liquido = False
        data_taxa_anterior: date | None = None
        achou_cabecalho = False
        for _, linhas in abas.items():
            mapa = self._mapear(linhas)
            if not mapa:
                continue
            achou_cabecalho = True
            cabecalho, indices, nomes = mapa
            for numero, linha in enumerate(linhas[cabecalho + 1 :], start=cabecalho + 2):
                texto_linha = _norm(" ".join(str(v or "") for v in linha))
                data = self._data(self._texto(linha, indices, "data_venda")) or self._data(
                    self._texto(linha, indices, "data_pagamento")
                )
                primeiro_campo = next((_norm(valor) for valor in linha if _norm(valor)), "")
                if data is None and re.fullmatch(r"(?:SUB)?(?:TOTAL(?:IS| GERAL| LIQUIDO| BRUTO)?|TOTAIS):?", primeiro_campo):
                    continue
                status = _norm(self._texto(linha, indices, "status"))
                # Venda que não gerou dinheiro: negada, recusada, cancelada, revertida, devolvida.
                sem_dinheiro = r"NEGAD[AO]|CANCELAD[AO]|NAO AUTORIZAD[AO]|RECUSAD[AO]|REVERTID[AO]|DEVOLVID[AO]|REFUNDED|CHARGED.BACK|REJECTED|CANCELL?ED"
                if re.search(sem_dinheiro, status) and not re.search(r"ESTORNO|CHARGEBACK", status):
                    resultado.ignorados += 1
                    continue
                bruto = self._valor(linha, indices, "bruto")
                liquido = self._valor(linha, indices, "liquido")
                taxa = self._valor(linha, indices, "taxa")
                antecipacao = self._valor(linha, indices, "taxa_antecipacao")
                if "taxa_antecipacao" in indices and bruto is not None and liquido is not None:
                    # MDR e antecipação vêm com frações de centavo: o descontado é bruto − líquido.
                    taxa = bruto - abs(liquido)
                elif taxa is not None and antecipacao:
                    taxa = abs(taxa) + abs(antecipacao)
                debito = self._valor(linha, indices, "debito")
                if bruto is None and liquido is None and not debito:
                    continue
                # Taxa avulsa do extrato de reembolso (ex.: "Taxa TPE" após o SubTotal):
                # sem data própria, herda a da taxa imediatamente anterior.
                taxa_avulsa = bool(re.match(r"(?:TAXA|TARIFA|SERVICO|MENSALIDADE)\b", _norm(self._texto(linha, indices, "descricao"))))
                if data is None and taxa_avulsa:
                    data = data_taxa_anterior
                data_taxa_anterior = data if taxa_avulsa else None
                if data is None:
                    resultado.erros.append(ErroLinha.de_linha(numero, "Data inválida", linha))
                    continue
                if taxa_avulsa or debito:
                    valor = abs(debito or bruto or liquido or Decimal("0"))
                    resultado.movimentos.append(Movimento(data, self._descricao(linha, indices, status), valor, SAIDA, documento=self._texto(linha, indices, "nsu"), linha_origem=numero, extras=self._extras(linha, indices, nomes)))
                    if taxa_avulsa or not bruto:
                        continue
                if taxa is None and bruto is not None and liquido is not None:
                    taxa = bruto - abs(liquido)
                taxa = abs(taxa or Decimal("0"))
                estorno = bool(re.search(r"ESTORNO|CANCELAMENTO|CHARGEBACK", status)) or (bruto is not None and bruto < 0)
                # No grupo B o líquido com sinal é o que saiu da conta; o bruto do estorno não.
                if estorno and not (self.p.grupo == "B" and liquido is not None):
                    valor = abs(bruto or liquido or Decimal("0"))
                    resultado.movimentos.append(Movimento(data, self._descricao(linha, indices, status), valor, SAIDA, documento=self._texto(linha, indices, "nsu"), linha_origem=numero, extras=self._extras(linha, indices, nomes)))
                    if liquido is not None:
                        conferidos += 1
                    continue
                # Lançamento sem venda (cessão, gravame, ajuste): bruto 0 e o líquido com sinal.
                sem_venda = bruto == 0 and bool(liquido)
                if self.p.grupo == "B" or bruto is None or sem_venda:
                    if liquido == 0:
                        resultado.ignorados += 1
                    elif liquido is not None:
                        tipo = SAIDA if liquido < 0 else ENTRADA
                        resultado.movimentos.append(Movimento(data, self._descricao(linha, indices, status), abs(liquido), tipo, documento=self._texto(linha, indices, "nsu"), linha_origem=numero, extras=self._extras(linha, indices, nomes)))
                    if sem_venda and self.p.grupo != "B":
                        continue
                    if not avisou_liquido:
                        resultado.avisos.append("Arquivo sem taxa detalhada: entradas pelo valor líquido")
                        avisou_liquido = True
                    continue
                valor_bruto = abs(bruto)
                extras = self._extras(linha, indices, nomes)
                resultado.movimentos.append(Movimento(data, self._descricao(linha, indices, status), valor_bruto, ENTRADA, documento=self._texto(linha, indices, "nsu"), linha_origem=numero, extras=extras))
                if taxa:
                    resultado.movimentos.append(Movimento(data, f"Taxa - {self._descricao(linha, indices, status)}", taxa, SAIDA, documento=self._texto(linha, indices, "nsu"), linha_origem=numero, extras=dict(extras)))
                if liquido is None:
                    continue
                encontrou_liquido = True
                conferidos += 1
                if abs(valor_bruto - taxa - abs(liquido)) > Decimal("0.01"):
                    divergentes += 1
                    resultado.erros.append(ErroLinha.de_linha(numero, "Bruto - taxa ≠ líquido", linha))
        if not achou_cabecalho:
            resultado.avisos.append("Cabeçalho de cartão não detectado.")
        if not encontrou_liquido:
            resultado.conferencia = "sem líquido para conferir"
        elif divergentes:
            resultado.conferencia = f"divergente ({divergentes} de {conferidos} linhas)"
        else:
            resultado.conferencia = "ok"
        return resultado

    def _descricao(self, linha: list, indices: dict[str, int], status: str) -> str:
        partes = [
            self._texto(linha, indices, "operacao")
            or self._texto(linha, indices, "descricao")
            or self._texto(linha, indices, "produto"),
            self._texto(linha, indices, "bandeira"),
        ]
        nsu = self._texto(linha, indices, "nsu")
        descricao = " ".join(parte for parte in partes if parte)
        if nsu:
            descricao = f"{descricao} NSU {nsu}".strip()
        return descricao or self._texto(linha, indices, "status") or limpar_texto(status) or "Venda de cartão"

    def _extras(self, linha: list, indices: dict[str, int], nomes: dict[int, str]) -> dict[str, str]:
        extras = {}
        for campo, rotulo in (("bandeira", "Bandeira"), ("produto", "Produto"), ("nsu", "NSU"), ("autorizacao", "Autorização"), ("parcela", "Parcela"), ("data_pagamento", "Data pagamento"), ("bruto", "Bruto"), ("liquido", "Líquido")):
            indice = indices.get(campo)
            if indice is None or indice >= len(linha) or linha[indice] in (None, ""):
                continue
            valor = parse_valor(linha[indice]) if campo in {"bruto", "liquido"} else linha[indice]
            extras[rotulo] = f"{valor:.2f}" if isinstance(valor, Decimal) else limpar_texto(valor)
        return extras
