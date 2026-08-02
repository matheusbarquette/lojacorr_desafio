import re
from django.core.exceptions import ValidationError


def _apenas_digitos(valor: str) -> str:
    """Remove pontos, barra e traço, deixando só os números."""
    return re.sub(r'\D', '', valor or '')


def _calcular_digito_verificador(base: str, pesos: list[int]) -> int:
    soma = sum(int(digito) * peso for digito, peso in zip(base, pesos))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def validar_cnpj(valor: str) -> None:
    """
    Valida um CNPJ (com ou sem formatação: '00.000.000/0000-00' ou '00000000000000').
    Levanta ValidationError se for inválido.
    """
    cnpj = _apenas_digitos(valor)

    if len(cnpj) != 14:
        raise ValidationError(f'CNPJ deve conter 14 dígitos (recebido: {len(cnpj)}).')

    # Rejeita sequências como '11111111111111', que passariam no cálculo mas não são CNPJs reais
    if cnpj == cnpj[0] * 14:
        raise ValidationError('CNPJ inválido.')

    pesos_dv1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_dv2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    dv1 = _calcular_digito_verificador(cnpj[:12], pesos_dv1)
    dv2 = _calcular_digito_verificador(cnpj[:12] + str(dv1), pesos_dv2)

    if cnpj[-2:] != f'{dv1}{dv2}':
        raise ValidationError('CNPJ inválido (dígito verificador não confere).')