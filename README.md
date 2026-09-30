# Conversor de Extratos

Aplicativo desktop para importar extratos bancários e relatórios de cartões, conferir lançamentos e exportar o resultado para Excel. A identificação do formato é feita pelo conteúdo do arquivo, não apenas pela extensão.

## Requisitos

- Windows 10 ou posterior para a interface gráfica e para o executável distribuído.
- Python 3.10 ou posterior para executar pelo código-fonte.
- Tkinter, normalmente incluído na instalação oficial do Python para Windows.

As dependências de leitura e exportação estão em `requirements.txt`: pdfplumber, openpyxl e xlrd.

## Instalação e execução

No PowerShell, na pasta do projeto:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

A janela permite selecionar um arquivo, conferir o tipo detectado, o período, os totais e as ocorrências, e gerar uma pasta de trabalho `.xlsx`. Arquivos maiores que 50 MB solicitam confirmação antes da importação.

## Executável Windows

Com Python e PyInstaller instalados (`python -m pip install -r requirements-dev.txt`), gere o executável de janela única:

```powershell
pyinstaller --clean --noconfirm conversor.spec
```

O resultado é `dist\ConversorExtratos.exe`. O aplicativo não requer uma instalação separada do Python na máquina de destino. O executável deve ser validado em uma instalação limpa do Windows antes de distribuição; ver limitações e o roteiro em `PLANO.md`.

## Arquivos suportados

Extratos: PDF com texto selecionável, OFX, TXT, CSV, XLS e XLSX. Há layouts reconhecidos para Banco do Brasil, Banestes, Banrisul, Bradesco, Caixa, Itaú, Inter, Omie, Safra, Santander, Sicoob, Sicredi, Unicred, Stone Conta, Conta Simples e Banco ABC, além de um leitor genérico de planilhas. A tabela completa de identificadores, nomes, tipos e bancos é gerada por `python tools/listar_layouts.py` e está versionada em [docs/layouts.md](docs/layouts.md).

Cartões: planilhas CSV, XLS e XLSX de Cielo, Stone, Getnet, Rede/Sipag, PagSeguro/PagBank, Mercado Pago, Safra e Sicredi, com fallback genérico. Quando o arquivo traz bruto e taxa, a taxa é lançada separadamente; relatórios com apenas o líquido podem ser importados com aviso de taxa não detalhada. As regras e o inventário das amostras estão em [docs/cartoes_regras.md](docs/cartoes_regras.md) e [docs/cartoes_inventario.md](docs/cartoes_inventario.md).

## Testes

Instale também as dependências de desenvolvimento e rode a suíte:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Para executar apenas os testes que usam os arquivos reais em `samples/`:

```powershell
python -m pytest -q -m amostras
```

Essa pasta contém dados locais ignorados pelo Git. Sem ela, os testes de amostras são ignorados; os demais testes continuam disponíveis.

Três testes importam **todas** as planilhas de cartão (completude, avaliação dos 176 arquivos e inventário; cerca de 10 min juntos) e ficam fora do `pytest -q` padrão pelo marcador `varredura`. Rode-os antes de cada entrega:

```powershell
python -m pytest -q -m varredura
```

(`-m amostras` também os inclui, porque substitui o filtro padrão.) Para recuperar `samples/` a partir dos arquivos compactados das pastas de origem, rode `python tools/extrair_amostras.py`.

## Adicionar um layout

1. Use `python tools/detectar.py <arquivo>` para inspecionar o tipo e as pontuações dos layouts atuais.
2. Implemente uma subclasse de `LayoutParser` no módulo apropriado em `extratos_app/parsers/` e registre-a com `@registrar`.
3. Use `python tools/avaliar.py <filtro>` para avaliar a amostra e verificar o resultado do parser.
4. Acrescente um teste com uma âncora real em `tests/`.
5. Atualize a referência correspondente em `tests/referencia_extratos.json` (ou `tests/baseline_cartoes.json`, para cartões).
6. Rode `python tools/avaliar.py --comparar tests/baseline_extratos.json` e confirme que a mudança não introduziu regressões. Atualize também [docs/layouts.md](docs/layouts.md).

## Limitações conhecidas

- PDFs digitalizados como imagem não são reconhecidos; é necessário OCR, que não faz parte do aplicativo.
- Arquivos protegidos por senha, arquivos vazios e arquivos compactados como ZIP não são importados diretamente.
- A detecção genérica permite tentar importar formatos de planilha não catalogados, mas não garante que o resultado esteja correto; revise os avisos e a conferência antes de usar os totais.
- Cartões (medição de 29/09/2026): **159 de 176** arquivos reconhecidos; **92** com conferência automática `ok` (bruto − taxa = líquido), 24 divergentes e 43 sem líquido para conferir. Os totais de **32** arquivos são conferidos por oráculo independente, com tolerância zero (`tests/test_oraculos_cartoes.py`). Os 10 PDFs e 7 planilhas/CSV não reconhecidos estão em [docs/cartoes_regras.md](docs/cartoes_regras.md).
- A tag `v1.0` foi criada **antes** das correções de `PLANO_CORRECOES.md` e não reflete o estado atual; mover ou substituir a tag depende de aprovação (E7.2).
- Algumas amostras de extratos permanecem divergentes ou sem saldos de referência. Consulte o [Anexo B do PLANO.md](PLANO.md#anexo-b--amostras-divergentes--sem-saldos) antes de interpretar a conferência como garantia de exatidão.
- A criação do executável pode ser feita nesta máquina; a aprovação de distribuição requer validar o binário em Windows sem Python, conforme o critério de T7.2 em `PLANO.md`.

## Arquivos de referência

- [PLANO.md](PLANO.md): escopo, critérios e roteiro ponta a ponta.
- [docs/layouts.md](docs/layouts.md): layouts registrados no código.
- [docs/cartoes_inventario.md](docs/cartoes_inventario.md): inventário de arquivos de cartões analisados.
- [docs/cartoes_regras.md](docs/cartoes_regras.md): critérios de classificação e lançamento de cartões.
