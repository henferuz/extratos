"""Cada módulo deste pacote registra um ou mais layouts via `@registrar`.

Os módulos são importados aqui de forma estática: no executável (PyInstaller) o pkgutil não
enxerga o pacote e imports dinâmicos não são empacotados. Ao criar um módulo de layout,
acrescente-o a este import (tests/test_empacotamento.py confere).
"""
from extratos_app.parsers import (  # noqa: F401 - importar registra os layouts
    base,
    cartoes_l1,
    mercado_pago,
    ofx,
    pdf_bancos,
    pdf_bb,
    pdf_efi,
    pdf_itau,
    planilha_base,
    planilhas_bancos,
    texto_base,
    txt_bancos,
)

MODULOS = tuple(
    modulo.__name__.rsplit(".", 1)[1]
    for modulo in (
        base, cartoes_l1, mercado_pago, ofx, pdf_bancos, pdf_bb, pdf_efi, pdf_itau,
        planilha_base, planilhas_bancos, texto_base, txt_bancos,
    )
)
