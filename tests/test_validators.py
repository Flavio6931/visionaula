"""Pruebas unitarias de la validación de cédula ecuatoriana."""

import pytest
from django.core.exceptions import ValidationError

from asistencia.validators import (
    digito_verificador,
    es_cedula_valida,
    normalizar_cedula,
    validar_cedula_ecuatoriana,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "cedula",
    ["1710034065", "0912345675", "0102030400", "2401234568", "3001234560", " 091234567-5 "],
)
def test_valid_ecuadorian_ids_are_accepted(cedula):
    validar_cedula_ecuatoriana(cedula)
    assert es_cedula_valida(cedula)


@pytest.mark.parametrize(
    ("cedula", "codigo"),
    [
        ("", "longitud"),
        ("123", "longitud"),
        ("17100340651", "longitud"),
        ("17100340AB", "longitud"),
        ("١٧١٠٠٣٤٠٦٥", "longitud"),  # dígitos no ASCII
        ("0010034065", "provincia"),
        ("2510034065", "provincia"),
        ("2910034065", "provincia"),
        ("1760034065", "tercer_digito"),
        ("1710034064", "verificador"),
    ],
)
def test_invalid_ecuadorian_ids_are_rejected_with_reason(cedula, codigo):
    with pytest.raises(ValidationError) as error:
        validar_cedula_ecuatoriana(cedula)
    assert error.value.code == codigo
    assert not es_cedula_valida(cedula)


def test_check_digit_algorithm():
    assert digito_verificador("171003406") == 5
    assert digito_verificador("010203040") == 0  # suma múltiplo de 10 -> verificador 0


def test_normalization_removes_spaces_and_hyphens():
    assert normalizar_cedula(" 091 234 567-5 ") == "0912345675"
    assert normalizar_cedula(None) == ""
