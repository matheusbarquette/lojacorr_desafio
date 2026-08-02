"""
Fixtures compartilhadas.

Princípio da suíte: NENHUM teste toca a internet. A URL da BrasilAPI aponta
para um host que não existe e todas as chamadas são interceptadas pelo respx —
se algum código tentar sair para a rede, o teste quebra em vez de ficar lento e
instável.
"""
from contextlib import contextmanager

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from seguradoras.models import Seguradora

# CNPJs válidos de verdade (passam no dígito verificador). Sem isso os testes
# esbarrariam na própria validação antes de exercitar a regra em teste.
CNPJS = [
    '33634567000179',
    '61273855000180',
    '07875747000132',
    '92845331000140',
    '44641243000184',
]

URL_BRASILAPI = 'http://brasilapi.test/api/cnpj/v1/{cnpj}'


def url_cnpj(cnpj: str) -> str:
    """URL que o respx deve interceptar para um dado CNPJ."""
    return URL_BRASILAPI.format(cnpj=cnpj)


def item(cnpj: str, nome: str = 'Seguradora Teste', uf: str = 'SP') -> dict:
    """Monta um item do payload de importação."""
    return {'nome': nome, 'cnpj': cnpj, 'uf': uf}


def criar_seguradora(cnpj: str, nome: str = 'Seguradora Teste', uf: str = 'SP', **extras):
    return Seguradora.objects.create(cnpj=cnpj, nome=nome, uf=uf, **extras)


@pytest.fixture(autouse=True)
def integracao_isolada(settings):
    settings.BRASILAPI_CNPJ_URL = URL_BRASILAPI
    settings.BRASILAPI_TIMEOUT = 1.0


@pytest.fixture(autouse=True)
def cache_limpo():
    """
    O cache em memória sobrevive entre testes do mesmo processo; sem limpar, a
    versão de cache de um teste vazaria para o seguinte.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def contar_queries():
    """
    Conta só as queries de dados, ignorando SAVEPOINT/RELEASE.

    Sem esse filtro a contagem varia conforme o Django gerencia savepoints, e o
    teste vira ruído em vez de garantia.
    """

    @contextmanager
    def _contexto():
        registro = {}
        with CaptureQueriesContext(connection) as ctx:
            yield registro
        registro['queries'] = [
            q['sql'] for q in ctx.captured_queries
            if 'SAVEPOINT' not in q['sql'].upper()
        ]
        registro['total'] = len(registro['queries'])

    return _contexto
