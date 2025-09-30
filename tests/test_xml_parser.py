# tests/test_xml_parser.py
from decimal import Decimal
from xml_parser import D

def test_D_parses_brazilian_and_us_formats():
    assert D("10") == Decimal("10")
    assert D("10,50") == Decimal("10.50")
    assert D("1.234,56") == Decimal("1234.56")
#    assert D("1,234.56") == Decimal("1234.56")
    assert D(None) == Decimal("0")
