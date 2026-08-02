"""Testes do GET /api/v1/seguradoras/ — paginação, filtros e cache."""
import pytest

from seguradoras.models import Seguradora

from .conftest import CNPJS, criar_seguradora

pytestmark = pytest.mark.django_db

URL = '/api/v1/seguradoras/'


@pytest.fixture
def catalogo():
    criar_seguradora(CNPJS[0], 'Alfa Seguros', 'SP')
    criar_seguradora(CNPJS[1], 'Beta Seguradora', 'RJ')
    criar_seguradora(CNPJS[2], 'Gama Alfa Seguros', 'SP')


# --- Paginação -------------------------------------------------------------

def test_resposta_vem_paginada(api, catalogo):
    corpo = api.get(URL).json()

    assert corpo['count'] == 3
    assert len(corpo['results']) == 3
    assert {'count', 'next', 'previous', 'results'} <= corpo.keys()


def test_respeita_o_page_size_pedido(api, catalogo):
    corpo = api.get(URL, {'page_size': 2}).json()

    assert corpo['count'] == 3
    assert len(corpo['results']) == 2
    assert corpo['next'] is not None


def test_page_size_tem_teto(api, catalogo):
    """Sem teto, ?page_size=99999 vira um jeito fácil de derrubar o banco."""
    assert len(api.get(URL, {'page_size': 99999}).json()['results']) <= 100


# --- Filtros ---------------------------------------------------------------

def test_filtra_por_uf(api, catalogo):
    corpo = api.get(URL, {'uf': 'RJ'}).json()

    assert corpo['count'] == 1
    assert corpo['results'][0]['nome'] == 'Beta Seguradora'


def test_filtro_de_uf_ignora_maiuscula(api, catalogo):
    assert api.get(URL, {'uf': 'sp'}).json()['count'] == 2


def test_filtra_por_nome_parcial(api, catalogo):
    assert api.get(URL, {'nome': 'alfa'}).json()['count'] == 2


def test_filtros_sao_combinaveis(api, catalogo):
    assert api.get(URL, {'nome': 'alfa', 'uf': 'RJ'}).json()['count'] == 0


# --- Cache -----------------------------------------------------------------

def test_segunda_chamada_vem_do_cache(api, catalogo):
    assert api.get(URL)['X-Cache'] == 'MISS'
    assert api.get(URL)['X-Cache'] == 'HIT'


def test_hit_de_cache_nao_consulta_o_banco(api, catalogo, contar_queries):
    api.get(URL)  # aquece

    with contar_queries() as registro:
        api.get(URL)

    assert registro['total'] == 0, registro['queries']


def test_querystrings_diferentes_sao_entradas_diferentes(api, catalogo):
    api.get(URL, {'uf': 'SP'})

    assert api.get(URL, {'uf': 'RJ'})['X-Cache'] == 'MISS'


def test_importacao_invalida_o_cache(api, catalogo, django_capture_on_commit_callbacks):
    api.get(URL)  # aquece

    # A invalidação roda em transaction.on_commit; dentro de um teste o commit
    # nunca acontece de verdade, então executamos os callbacks na mão.
    with django_capture_on_commit_callbacks(execute=True):
        api.post(
            '/api/v1/seguradoras/importar/',
            [{'nome': 'Nova', 'cnpj': CNPJS[3], 'uf': 'MG'}],
            format='json',
        )

    resposta = api.get(URL)
    assert resposta['X-Cache'] == 'MISS'
    assert resposta.json()['count'] == Seguradora.objects.count() == 4
