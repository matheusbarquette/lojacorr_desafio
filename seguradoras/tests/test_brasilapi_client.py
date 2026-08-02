"""
Testes do cliente HTTP da BrasilAPI.

Toda a comunicação é simulada com respx (o equivalente do `responses` para
httpx). O mock acontece na camada de TRANSPORTE, não na nossa função: o código
real do cliente é exercitado, inclusive o tratamento de erro — justamente a
parte difícil de reproduzir contra a API de verdade.
"""
import httpx
import pytest

from seguradoras.integrations.brasilapi import BrasilAPIClient, DadosCNPJ
from seguradoras.integrations.exceptions import (
    CNPJNaoEncontrado,
    LimiteDeRequisicoesExcedido,
    ServicoIndisponivel,
)

from .conftest import CNPJS, url_cnpj

CNPJ = CNPJS[0]

RESPOSTA_OK = {
    'cnpj': CNPJ,
    'razao_social': 'ALFA SEGUROS S.A.',
    'nome_fantasia': 'ALFA SEGUROS',
    'descricao_situacao_cadastral': 'ATIVA',
    'municipio': 'SAO PAULO',  # campo que não usamos
}


@pytest.fixture
def cliente():
    with BrasilAPIClient() as c:
        yield c


def test_sucesso_devolve_apenas_os_campos_do_dominio(cliente, respx_mock):
    respx_mock.get(url_cnpj(CNPJ)).mock(return_value=httpx.Response(200, json=RESPOSTA_OK))

    assert cliente.consultar(CNPJ) == DadosCNPJ(
        nome_fantasia='ALFA SEGUROS', situacao_cadastral='ATIVA'
    )


def test_usa_razao_social_quando_nao_ha_nome_fantasia(cliente, respx_mock):
    respx_mock.get(url_cnpj(CNPJ)).mock(
        return_value=httpx.Response(200, json={**RESPOSTA_OK, 'nome_fantasia': ''})
    )

    assert cliente.consultar(CNPJ).nome_fantasia == 'ALFA SEGUROS S.A.'


def test_respeita_o_tamanho_maximo_das_colunas(cliente, respx_mock):
    respx_mock.get(url_cnpj(CNPJ)).mock(
        return_value=httpx.Response(200, json={'nome_fantasia': 'A' * 400})
    )

    assert len(cliente.consultar(CNPJ).nome_fantasia) == 255


def test_campos_ausentes_viram_string_vazia(cliente, respx_mock):
    respx_mock.get(url_cnpj(CNPJ)).mock(return_value=httpx.Response(200, json={}))

    assert cliente.consultar(CNPJ) == DadosCNPJ(nome_fantasia='', situacao_cadastral='')


def test_a_consulta_usa_timeout(cliente, respx_mock, settings):
    """Sem timeout, uma API lenta prenderia o worker indefinidamente."""
    rota = respx_mock.get(url_cnpj(CNPJ)).mock(return_value=httpx.Response(200, json={}))

    cliente.consultar(CNPJ)

    assert rota.calls.last.request.extensions['timeout']['connect'] == settings.BRASILAPI_TIMEOUT


# --------------------------------------------------------------------------- #
# Falhas. O tipo da exceção é o que diz ao worker se vale tentar de novo.
# --------------------------------------------------------------------------- #


def test_404_vira_erro_definitivo(cliente, respx_mock):
    respx_mock.get(url_cnpj(CNPJ)).mock(return_value=httpx.Response(404))

    with pytest.raises(CNPJNaoEncontrado):
        cliente.consultar(CNPJ)


@pytest.mark.parametrize('status', [500, 502, 503])
def test_erro_do_servidor_vira_erro_transitorio(cliente, respx_mock, status):
    respx_mock.get(url_cnpj(CNPJ)).mock(return_value=httpx.Response(status))

    with pytest.raises(ServicoIndisponivel):
        cliente.consultar(CNPJ)


def test_429_vira_excecao_propria_de_rate_limit(cliente, respx_mock):
    """
    O worker precisa distinguir 429 dos outros erros transitórios: nele a rodada
    para, e sem penalizar registro nenhum.
    """
    respx_mock.get(url_cnpj(CNPJ)).mock(return_value=httpx.Response(429))

    with pytest.raises(LimiteDeRequisicoesExcedido):
        cliente.consultar(CNPJ)


def test_rate_limit_continua_sendo_um_erro_transitorio(cliente, respx_mock):
    """A herança importa: quem só conhece ServicoIndisponivel continua tratando."""
    respx_mock.get(url_cnpj(CNPJ)).mock(return_value=httpx.Response(429))

    with pytest.raises(ServicoIndisponivel):
        cliente.consultar(CNPJ)


def test_timeout_vira_erro_transitorio(cliente, respx_mock):
    respx_mock.get(url_cnpj(CNPJ)).mock(side_effect=httpx.ConnectTimeout('estourou'))

    with pytest.raises(ServicoIndisponivel):
        cliente.consultar(CNPJ)


def test_api_fora_do_ar_vira_erro_transitorio(cliente, respx_mock):
    respx_mock.get(url_cnpj(CNPJ)).mock(side_effect=httpx.ConnectError('dns'))

    with pytest.raises(ServicoIndisponivel):
        cliente.consultar(CNPJ)


def test_corpo_que_nao_e_json_vira_erro_transitorio(cliente, respx_mock):
    respx_mock.get(url_cnpj(CNPJ)).mock(
        return_value=httpx.Response(200, text='<html>erro</html>')
    )

    with pytest.raises(ServicoIndisponivel):
        cliente.consultar(CNPJ)


def test_uma_consulta_faz_uma_requisicao(cliente, respx_mock):
    """Sem retry interno: quem reprocessa é a próxima rodada do worker."""
    rota = respx_mock.get(url_cnpj(CNPJ)).mock(return_value=httpx.Response(500))

    with pytest.raises(ServicoIndisponivel):
        cliente.consultar(CNPJ)

    assert rota.call_count == 1
