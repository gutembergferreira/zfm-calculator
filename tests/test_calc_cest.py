import pandas as pd
import pytest
from types import SimpleNamespace

import pandas as pd
import pytest
from types import SimpleNamespace

from calc import MotorCalculo


def _fake_item(cest: str, ncm: str = "09030091"):
    return SimpleNamespace(
        nItem=1,
        cProd="0903",
        xProd="BUCHA",
        ncm=ncm,
        cst="060",
        cfop="5102",
        qCom=1,
        vUnCom=100,
        vProd=100,
        vFrete=0,
        vIPI=0,
        vOutro=0,
        vICMSDeson=0,
        cest=cest,
    )


@pytest.fixture
def motor_with_cest_rules():
    df = pd.DataFrame(
        [
            {"NCM": "0903.00.91", "CEST": "0000000", "UF": "AM", "MVA %": "70", "APLICA_ST": "1"},
            {"NCM": "0903.00.91", "CEST": "1234567", "UF": "AM", "MVA %": "59", "APLICA_ST": "1"},
            {"NCM": "0903.00.91", "CEST": "", "UF": "AM", "MVA %": "50", "APLICA_ST": "1"},
        ]
    )
    return MotorCalculo({"planilha": df})


@pytest.fixture
def motor_with_numeric_cest():
    df = pd.DataFrame(
        [
            {"NCM": "3926.90", "CEST": 1002000.0, "UF": "AM", "MVA %": "70", "APLICA_ST": "1"},
            {"NCM": "3926.90", "CEST": "", "UF": "AM", "MVA %": "59", "APLICA_ST": "1"},
        ]
    )
    return MotorCalculo({"planilha": df})


@pytest.fixture
def motor_with_leading_zero_cest():
    df = pd.DataFrame(
        [
            {"NCM": "6804.22.11", "CEST": 800300.0, "UF": "AM", "MVA %": "45", "APLICA_ST": "1"},
            {"NCM": "6804.22.11", "CEST": "", "UF": "AM", "MVA %": "10", "APLICA_ST": "1"},
        ]
    )
    return MotorCalculo({"planilha": df})


def test_motor_usa_mva_de_cest_correspondente(motor_with_cest_rules):
    item = _fake_item("0000000")
    resultado = motor_with_cest_rules.calcula_st(item, "SP", "AM")
    assert resultado.memoria["MARGEM_DE_VALOR_AGREGADO_MVA"] == pytest.approx(70.0)


def test_motor_usa_mva_especifica_para_outro_cest(motor_with_cest_rules):
    item = _fake_item("1234567")
    resultado = motor_with_cest_rules.calcula_st(item, "SP", "AM")
    assert resultado.memoria["MARGEM_DE_VALOR_AGREGADO_MVA"] == pytest.approx(59.0)


def test_motor_quando_sem_match_de_cest_usa_regra_generica(motor_with_cest_rules):
    item = _fake_item("9999999")
    resultado = motor_with_cest_rules.calcula_st(item, "SP", "AM")
    assert resultado.memoria["MARGEM_DE_VALOR_AGREGADO_MVA"] == pytest.approx(50.0)


def test_motor_cest_float_com_decimal_zero(motor_with_numeric_cest):
    item = _fake_item("1002000", ncm="39269000")
    resultado = motor_with_numeric_cest.calcula_st(item, "SP", "AM")
    assert resultado.memoria["MARGEM_DE_VALOR_AGREGADO_MVA"] == pytest.approx(70.0)


def test_motor_cest_float_preserva_codigo_com_zero_a_esquerda(motor_with_leading_zero_cest):
    item = _fake_item("0800300", ncm="68042211")
    resultado = motor_with_leading_zero_cest.calcula_st(item, "SP", "AM")
    assert resultado.memoria["MARGEM_DE_VALOR_AGREGADO_MVA"] == pytest.approx(45.0)
