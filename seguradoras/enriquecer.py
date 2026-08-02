import logging
from django.utils import timezone
from .cache_utils import invalidar_listagem
from .integrations.brasilapi import ClienteCNPJ
from .integrations.exceptions import (
    CNPJNaoEncontrado,
    LimiteDeRequisicoesExcedido,
    ServicoIndisponivel,
)
from .models import Seguradora

logger = logging.getLogger('seguradoras')


def enriquecer_pendentes(
    cliente: ClienteCNPJ,
    tamanho_lote: int = 50,
    max_tentativas: int = 3,
) -> dict:
    """
    Consulta a BrasilAPI para as seguradoras ainda não enriquecidas e preenche
    `nome_fantasia` e `situacao_cadastral`.

    "Pendente" = `enriquecido_em` vazio. Não precisamos de uma tabela de fila:
    o próprio campo que marca a conclusão já define quem falta.

    O tratamento depende do TIPO da falha:

      - `CNPJNaoEncontrado` (404): resposta definitiva. O registro sai da fila na
        hora, porque reconsultar todo dia não vai fazer o CNPJ passar a existir.
      - `LimiteDeRequisicoesExcedido` (429): a rodada inteira para, e NINGUÉM é
        penalizado. Ver o comentário no laço.
      - `ServicoIndisponivel` (timeout, rede, 5xx): falha transitória do próprio
        registro. Incrementa `tentativas` e ele volta na próxima rodada, até o
        limite de `max_tentativas`.

    Em todos os casos o registro CONTINUA com os dados básicos e nada trava —
    que é o que o desafio pede.
    """
    pendentes = Seguradora.objects.filter(
        enriquecido_em__isnull=True,
        tentativas__lt=max_tentativas,
    )[:tamanho_lote]

    resultado = {'enriquecidas': 0, 'nao_encontradas': 0, 'falhas': 0}
    agora = timezone.now()

    for seguradora in pendentes:
        try:
            dados = cliente.consultar(seguradora.cnpj)
        except LimiteDeRequisicoesExcedido as exc:
            logger.warning('%s Encerrando a rodada; a fila continua na próxima.', exc)
            break
        except CNPJNaoEncontrado:
            logger.warning('CNPJ %s não existe na BrasilAPI; sai da fila.', seguradora.cnpj)
            seguradora.tentativas = max_tentativas
            resultado['nao_encontradas'] += 1
        except ServicoIndisponivel as exc:
            logger.warning('Falha transitória no CNPJ %s: %s', seguradora.cnpj, exc)
            seguradora.tentativas += 1
            resultado['falhas'] += 1
        except Exception:
            logger.exception('Erro inesperado ao enriquecer o CNPJ %s.', seguradora.cnpj)
            seguradora.tentativas += 1
            resultado['falhas'] += 1
        else:
            seguradora.nome_fantasia = dados.nome_fantasia
            seguradora.situacao_cadastral = dados.situacao_cadastral
            seguradora.enriquecido_em = agora
            seguradora.tentativas += 1
            resultado['enriquecidas'] += 1
            logger.info('CNPJ %s enriquecido.', seguradora.cnpj)

        seguradora.save(update_fields=[
            'nome_fantasia', 'situacao_cadastral', 'enriquecido_em',
            'tentativas', 'atualizado_em',
        ])

    if resultado['enriquecidas']:
        # A listagem passou a devolver dados diferentes.
        invalidar_listagem()

    return resultado
