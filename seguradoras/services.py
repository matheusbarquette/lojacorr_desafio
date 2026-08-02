from django.db import transaction
from .cache_utils import invalidar_listagem
from .models import Seguradora


@transaction.atomic
def importar_em_lote(itens: list[dict]) -> dict:
    """
    Recebe itens JÁ VALIDADOS (nome, cnpj, uf) e faz o upsert em LOTE, com um
    número FIXO de queries — independente de quantos itens vierem no payload:

        1 SELECT  -> quais CNPJs do lote já existem
      + 1 INSERT  -> bulk_create dos novos
      + 1 UPDATE  -> bulk_update dos que já existiam
      = no máximo 3 queries, em vez de 2 ou 3 POR ITEM.

    É esse o ponto do requisito "tratamento eficiente da regra de Upsert
    (evitando consultas excessivas ao banco)".

    Note que o update toca APENAS `nome` e `uf`. Reimportar o cadastro básico
    não pode apagar `nome_fantasia`/`situacao_cadastral`, que são o resultado do
    trabalho do worker de enriquecimento.
    """
    cnpjs = [item['cnpj'] for item in itens]

    # uma única consulta para descobrir quem já existe.
    existentes = {
        seguradora.cnpj: seguradora
        for seguradora in Seguradora.objects.filter(cnpj__in=cnpjs)
    }

    a_criar: list[Seguradora] = []
    a_atualizar: list[Seguradora] = []

    for item in itens:
        seguradora = existentes.get(item['cnpj'])
        if seguradora is None:
            a_criar.append(Seguradora(**item))
        else:
            seguradora.nome = item['nome']
            seguradora.uf = item['uf']
            a_atualizar.append(seguradora)

    if a_criar:
        Seguradora.objects.bulk_create(a_criar)
    if a_atualizar:
        Seguradora.objects.bulk_update(a_atualizar, ['nome', 'uf'])

    # A listagem em cache acabou de ficar desatualizada. `on_commit` garante que
    # a invalidação só acontece se a transação for realmente commitada — se der
    # rollback, o cache continua válido e não invalidamos à toa.
    transaction.on_commit(invalidar_listagem)

    return {
        'criadas': len(a_criar),
        'atualizadas': len(a_atualizar),
        'total': len(itens),
    }
