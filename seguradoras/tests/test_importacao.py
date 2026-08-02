"""Testes do POST /api/v1/seguradoras/importar/."""
import pytest
from django.utils import timezone

from seguradoras.models import Seguradora

from .conftest import CNPJS, item

pytestmark = pytest.mark.django_db

URL = '/api/v1/seguradoras/importar/'


def test_importa_e_devolve_201_com_contagem(api):
    resposta = api.post(
        URL,
        [item(CNPJS[0], 'Alfa'), item(CNPJS[1], 'Beta', 'RJ')],
        format='json',
    )

    assert resposta.status_code == 201
    assert resposta.json() == {'criadas': 2, 'atualizadas': 0, 'total': 2}
    assert Seguradora.objects.count() == 2


def test_cnpj_e_gravado_sem_formatacao(api):
    api.post(URL, [item('33.634.567/0001-79', 'Alfa')], format='json')

    assert Seguradora.objects.get().cnpj == CNPJS[0]


def test_uf_e_normalizada_para_maiuscula(api):
    api.post(URL, [item(CNPJS[0], 'Alfa', 'sp')], format='json')

    assert Seguradora.objects.get().uf == 'SP'


def test_upsert_atualiza_em_vez_de_duplicar(api):
    api.post(URL, [item(CNPJS[0], 'Nome Antigo', 'SP')], format='json')

    resposta = api.post(URL, [item(CNPJS[0], 'Nome Novo', 'RJ')], format='json')

    assert resposta.json() == {'criadas': 0, 'atualizadas': 1, 'total': 1}
    assert Seguradora.objects.count() == 1

    seguradora = Seguradora.objects.get()
    assert seguradora.nome == 'Nome Novo'
    assert seguradora.uf == 'RJ'


def test_upsert_com_cnpj_formatado_encontra_o_registro_existente(api):
    api.post(URL, [item(CNPJS[0], 'Alfa')], format='json')

    api.post(URL, [item('33.634.567/0001-79', 'Alfa S.A.')], format='json')

    assert Seguradora.objects.count() == 1
    assert Seguradora.objects.get().nome == 'Alfa S.A.'


def test_upsert_preserva_dados_ja_enriquecidos(api):
    """Reimportar o cadastro básico não pode apagar o trabalho do worker."""
    api.post(URL, [item(CNPJS[0], 'Alfa')], format='json')
    Seguradora.objects.update(
        nome_fantasia='Alfa Seguros',
        situacao_cadastral='ATIVA',
        enriquecido_em=timezone.now(),
    )

    api.post(URL, [item(CNPJS[0], 'Alfa S.A.')], format='json')

    seguradora = Seguradora.objects.get()
    assert seguradora.nome == 'Alfa S.A.'
    assert seguradora.nome_fantasia == 'Alfa Seguros'
    assert seguradora.situacao_cadastral == 'ATIVA'
    assert seguradora.enriquecido_em is not None


def test_custo_em_queries_nao_cresce_com_o_tamanho_do_lote(api, contar_queries):
    """O upsert não pode virar N+1: 5 itens têm que custar o mesmo que 1."""
    with contar_queries() as um_item:
        api.post(URL, [item(CNPJS[0], 'Só uma')], format='json')

    Seguradora.objects.all().delete()

    itens = [item(cnpj, f'Seguradora {i}') for i, cnpj in enumerate(CNPJS)]
    with contar_queries() as cinco_itens:
        api.post(URL, itens, format='json')

    # 1 SELECT (quais CNPJs já existem) + 1 INSERT em lote, nos dois casos.
    assert um_item['total'] == 2, um_item['queries']
    assert cinco_itens['total'] == 2, cinco_itens['queries']


def test_importacao_nao_chama_a_api_externa(api, respx_mock):
    """O POST responde na hora; enriquecer é responsabilidade do worker."""
    api.post(URL, [item(CNPJS[0])], format='json')

    assert not respx_mock.calls


def test_registro_novo_nasce_pendente_de_enriquecimento(api):
    api.post(URL, [item(CNPJS[0])], format='json')

    seguradora = Seguradora.objects.get()
    assert seguradora.enriquecido_em is None
    assert seguradora.nome_fantasia == ''


# --------------------------------------------------------------------------- #
# Validação: entrada ruim rejeita o lote inteiro e não grava nada.
# --------------------------------------------------------------------------- #


def test_rejeita_cnpj_invalido(api):
    resposta = api.post(URL, [item('12345678000100')], format='json')

    assert resposta.status_code == 400
    assert 'cnpj' in resposta.json()[0]
    assert not Seguradora.objects.exists()


def test_rejeita_uf_inexistente(api):
    resposta = api.post(URL, [item(CNPJS[0], uf='XX')], format='json')

    assert resposta.status_code == 400
    assert 'uf' in resposta.json()[0]


def test_rejeita_cnpj_repetido_no_mesmo_envio(api):
    resposta = api.post(
        URL,
        [item(CNPJS[0], 'Alfa'), item(CNPJS[0], 'Beta')],
        format='json',
    )

    assert resposta.status_code == 400
    assert CNPJS[0] in str(resposta.json())
    assert not Seguradora.objects.exists()


def test_rejeita_lista_vazia(api):
    assert api.post(URL, [], format='json').status_code == 400


def test_rejeita_payload_que_nao_e_lista(api):
    assert api.post(URL, item(CNPJS[0]), format='json').status_code == 400


def test_um_item_ruim_impede_a_gravacao_do_lote_inteiro(api):
    resposta = api.post(
        URL,
        [item(CNPJS[0], 'Válida'), item('00000000000000', 'Inválida')],
        format='json',
    )

    assert resposta.status_code == 400
    assert not Seguradora.objects.exists()
