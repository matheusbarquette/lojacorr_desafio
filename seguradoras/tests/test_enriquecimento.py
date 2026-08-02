"""
Testes da regra de enriquecimento.

Aqui o cliente HTTP é substituído por duplos que implementam o `ClienteCNPJ`.
É a vantagem de depender de uma interface e não da lib: dá para testar a regra
(quem sai da fila, contagem de tentativas, contadores) sem simular HTTP — isso
já está coberto em `test_brasilapi_client.py`.
"""
import httpx
import pytest
from django.core.management import call_command

from seguradoras.enriquecer import enriquecer_pendentes
from seguradoras.integrations.brasilapi import DadosCNPJ
from seguradoras.integrations.exceptions import (
    CNPJNaoEncontrado,
    LimiteDeRequisicoesExcedido,
    ServicoIndisponivel,
)
from seguradoras.models import Seguradora

from .conftest import CNPJS, criar_seguradora, url_cnpj

pytestmark = pytest.mark.django_db

DADOS = DadosCNPJ(nome_fantasia='Alfa Seguros', situacao_cadastral='ATIVA')


class ClienteFake:
    """Responde conforme o mapa; CNPJ ausente vira `CNPJNaoEncontrado`."""

    def __init__(self, respostas: dict[str, DadosCNPJ] | None = None):
        self.respostas = respostas or {}
        self.chamadas: list[str] = []

    def consultar(self, cnpj: str) -> DadosCNPJ:
        self.chamadas.append(cnpj)
        if cnpj not in self.respostas:
            raise CNPJNaoEncontrado(cnpj)
        return self.respostas[cnpj]


class ClienteIndisponivel:
    def __init__(self):
        self.chamadas: list[str] = []

    def consultar(self, cnpj: str) -> DadosCNPJ:
        self.chamadas.append(cnpj)
        raise ServicoIndisponivel('API fora do ar')


class ClienteComLimite:
    """Responde normalmente até `ate`; da consulta seguinte em diante, 429."""

    def __init__(self, respostas: dict[str, DadosCNPJ], ate: int):
        self.respostas = respostas
        self.ate = ate
        self.chamadas: list[str] = []

    def consultar(self, cnpj: str) -> DadosCNPJ:
        self.chamadas.append(cnpj)
        if len(self.chamadas) > self.ate:
            raise LimiteDeRequisicoesExcedido('devagar')
        return self.respostas[cnpj]


def test_sucesso_preenche_os_campos_e_sai_da_fila():
    criar_seguradora(CNPJS[0], 'Alfa')

    resultado = enriquecer_pendentes(ClienteFake({CNPJS[0]: DADOS}))

    assert resultado == {'enriquecidas': 1, 'nao_encontradas': 0, 'falhas': 0}
    seguradora = Seguradora.objects.get()
    assert seguradora.nome == 'Alfa'  # o dado do payload é preservado
    assert seguradora.nome_fantasia == 'Alfa Seguros'
    assert seguradora.situacao_cadastral == 'ATIVA'
    assert seguradora.enriquecido_em is not None


def test_api_fora_do_ar_mantem_os_dados_basicos():
    """Requisito do desafio: a API externa indisponível não trava o sistema."""
    criar_seguradora(CNPJS[0], 'Alfa', 'SP')

    resultado = enriquecer_pendentes(ClienteIndisponivel())

    assert resultado['falhas'] == 1
    seguradora = Seguradora.objects.get()
    assert seguradora.nome == 'Alfa'
    assert seguradora.uf == 'SP'
    assert seguradora.nome_fantasia == ''
    assert seguradora.enriquecido_em is None
    assert seguradora.tentativas == 1


def test_falha_transitoria_e_reprocessada_na_proxima_rodada():
    criar_seguradora(CNPJS[0])
    cliente = ClienteIndisponivel()

    enriquecer_pendentes(cliente)
    enriquecer_pendentes(cliente)

    assert len(cliente.chamadas) == 2
    assert Seguradora.objects.get().tentativas == 2


def test_falha_transitoria_para_depois_do_limite_de_tentativas():
    criar_seguradora(CNPJS[0], tentativas=3)
    cliente = ClienteIndisponivel()

    resultado = enriquecer_pendentes(cliente, max_tentativas=3)

    assert resultado == {'enriquecidas': 0, 'nao_encontradas': 0, 'falhas': 0}
    assert cliente.chamadas == []  # nem chegou a bater na API


def test_cnpj_inexistente_sai_da_fila_na_primeira_tentativa():
    """404 é definitivo: reconsultar não vai fazer o CNPJ passar a existir."""
    criar_seguradora(CNPJS[0])
    cliente = ClienteFake()

    primeira = enriquecer_pendentes(cliente, max_tentativas=3)
    segunda = enriquecer_pendentes(cliente, max_tentativas=3)

    assert primeira['nao_encontradas'] == 1
    assert segunda == {'enriquecidas': 0, 'nao_encontradas': 0, 'falhas': 0}
    assert len(cliente.chamadas) == 1  # não insistiu
    assert Seguradora.objects.get().nome_fantasia == ''


# --------------------------------------------------------------------------- #
# Rate limit (429). Cenário observado em produção com um lote de 50: depois de
# ~30 consultas a BrasilAPI começou a recusar. Sem o tratamento abaixo, o worker
# martelava os 18 restantes e gastava uma tentativa de cada um -- duas rodadas
# assim e registros perfeitamente válidos seriam descartados de vez.
# --------------------------------------------------------------------------- #


def test_rate_limit_encerra_a_rodada_sem_consultar_os_seguintes():
    for cnpj in CNPJS[:5]:
        criar_seguradora(cnpj)
    cliente = ClienteComLimite({cnpj: DADOS for cnpj in CNPJS}, ate=2)

    resultado = enriquecer_pendentes(cliente)

    assert resultado['enriquecidas'] == 2
    # 2 sucessos + 1 que tomou 429. Os outros 2 nem chegaram a ser consultados.
    assert len(cliente.chamadas) == 3


def test_rate_limit_nao_gasta_tentativa_de_ninguem():
    """A recusa é pelo nosso ritmo, não por defeito do registro."""
    for cnpj in CNPJS[:3]:
        criar_seguradora(cnpj)
    cliente = ClienteComLimite({cnpj: DADOS for cnpj in CNPJS}, ate=0)

    enriquecer_pendentes(cliente)

    pendentes = Seguradora.objects.filter(enriquecido_em__isnull=True)
    assert pendentes.count() == 3
    assert [s.tentativas for s in pendentes] == [0, 0, 0]


def test_rate_limit_nao_conta_como_falha():
    criar_seguradora(CNPJS[0])

    resultado = enriquecer_pendentes(ClienteComLimite({}, ate=0))

    assert resultado == {'enriquecidas': 0, 'nao_encontradas': 0, 'falhas': 0}


def test_fila_intacta_e_processada_na_rodada_seguinte():
    """Depois que a janela do limite passa, ninguém foi perdido."""
    for cnpj in CNPJS[:3]:
        criar_seguradora(cnpj)
    respostas = {cnpj: DADOS for cnpj in CNPJS}

    enriquecer_pendentes(ClienteComLimite(respostas, ate=0))   # rodada com 429
    resultado = enriquecer_pendentes(ClienteFake(respostas))   # API normalizou

    assert resultado['enriquecidas'] == 3
    assert not Seguradora.objects.filter(enriquecido_em__isnull=True).exists()


def test_erro_inesperado_e_contido_como_falha():
    """Um bug em um registro não pode derrubar o worker e parar a fila."""
    criar_seguradora(CNPJS[0])

    class ClienteQuebrado:
        def consultar(self, cnpj):
            raise RuntimeError('bug inesperado')

    assert enriquecer_pendentes(ClienteQuebrado())['falhas'] == 1


def test_ignora_quem_ja_foi_enriquecido():
    criar_seguradora(CNPJS[0])
    cliente = ClienteFake({CNPJS[0]: DADOS})
    enriquecer_pendentes(cliente)

    resultado = enriquecer_pendentes(cliente)

    assert resultado == {'enriquecidas': 0, 'nao_encontradas': 0, 'falhas': 0}
    assert len(cliente.chamadas) == 1


def test_falha_de_um_registro_nao_impede_os_demais():
    criar_seguradora(CNPJS[0], 'Existe')
    criar_seguradora(CNPJS[1], 'Não existe')

    resultado = enriquecer_pendentes(ClienteFake({CNPJS[0]: DADOS}))

    assert resultado == {'enriquecidas': 1, 'nao_encontradas': 1, 'falhas': 0}


def test_tamanho_lote_controla_o_tamanho_da_rodada():
    for cnpj in CNPJS[:3]:
        criar_seguradora(cnpj)
    cliente = ClienteFake({cnpj: DADOS for cnpj in CNPJS})

    assert enriquecer_pendentes(cliente, tamanho_lote=2)['enriquecidas'] == 2


def test_fila_vazia_nao_chama_a_api():
    cliente = ClienteFake()

    assert enriquecer_pendentes(cliente) == {'enriquecidas': 0, 'nao_encontradas': 0, 'falhas': 0}
    assert cliente.chamadas == []


def test_command_enriquece_a_fila(respx_mock, capsys):
    """
    O command é o que o container worker executa. Aqui o respx entra de novo,
    porque este teste cobre a fiação completa: command -> cliente real -> banco.
    """
    criar_seguradora(CNPJS[0])
    respx_mock.get(url_cnpj(CNPJS[0])).mock(
        return_value=httpx.Response(200, json={
            'nome_fantasia': 'Alfa Seguros',
            'descricao_situacao_cadastral': 'ATIVA',
        })
    )

    call_command('enriquecer_seguradoras')

    assert '1 enriquecida(s)' in capsys.readouterr().out
    assert Seguradora.objects.get().nome_fantasia == 'Alfa Seguros'
