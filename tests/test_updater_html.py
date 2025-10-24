import pandas as pd
import pytest

from updater import normalize_st_am, parse_st_am_html


def test_parse_st_am_html_extracts_table():
    html = """
    <html>
      <body>
        <table>
          <tr><th>NCM/SH</th><th>CEST</th><th>Substituição Tributária</th></tr>
          <tr><td>12.34.56.78</td><td>12.345.67</td><td>Sim</td></tr>
          <tr><td>87.65.43.21</td><td></td><td>Não</td></tr>
        </table>
      </body>
    </html>
    """
    df = parse_st_am_html(html)
    assert list(df.columns) == ["NCM/SH", "CEST", "SUBSTITUIÇÃO TRIBUTÁRIA"]
    assert len(df.index) == 2


def test_normalize_st_am_handles_substituicao_column():
    df = pd.DataFrame(
        [
            {"NCM/SH": "12.34.56.78", "CEST": "12.345.67", "SUBSTITUIÇÃO TRIBUTÁRIA": "Sim"},
            {"NCM/SH": "87.65.43.21", "CEST": "", "SUBSTITUIÇÃO TRIBUTÁRIA": "Não"},
        ]
    )

    tables = normalize_st_am(df)
    assert "st_regras" in tables
    st_regras = tables["st_regras"]
    assert list(st_regras.columns) == [
        "ATIVO",
        "NCM",
        "CEST",
        "CST_INCLUIR",
        "CST_EXCLUIR",
        "CFOP_INI",
        "CFOP_FIM",
        "ST_APLICA",
    ]
    assert len(st_regras.index) == 2
    primeira = st_regras.iloc[0]
    segunda = st_regras.iloc[1]
    assert primeira["NCM"] == "12345678"
    assert primeira["ST_APLICA"] == 1
    assert primeira["ATIVO"] == 1
    assert segunda["ST_APLICA"] == 0
    assert segunda["ATIVO"] == 0
