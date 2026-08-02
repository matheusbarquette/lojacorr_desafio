"""Testes da validação de CNPJ."""
import pytest
from django.core.exceptions import ValidationError

from seguradoras.validators import validar_cnpj

from .conftest import CNPJS


@pytest.mark.parametrize('cnpj', CNPJS)
def test_aceita_cnpj_valido(cnpj):
    validar_cnpj(cnpj)  # não deve levantar


def test_aceita_cnpj_formatado():
    validar_cnpj('33.634.567/0001-79')


@pytest.mark.parametrize(
    'cnpj, motivo',
    [
        ('33634567000178', 'dígito verificador errado'),
        ('123', 'menos de 14 dígitos'),
        ('336345670001790', 'mais de 14 dígitos'),
        ('11111111111111', 'sequência de dígitos iguais passa no cálculo, mas não é CNPJ real'),
        ('', 'vazio'),
    ],
)
def test_rejeita_cnpj_invalido(cnpj, motivo):
    with pytest.raises(ValidationError):
        validar_cnpj(cnpj)
