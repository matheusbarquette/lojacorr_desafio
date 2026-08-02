from rest_framework.pagination import PageNumberPagination


class SeguradoraPagination(PageNumberPagination):
    """
    Paginação padrão da API.

    Usa PageNumberPagination (?page=2) por ser a mais previsível para um
    catálogo consultado por filtro. O cliente pode ajustar o tamanho da página
    com ?page_size=, até um teto de 100 -- o teto evita que alguém peça
    ?page_size=999999 e derrube o banco.
    """

    page_size_query_param = 'page_size'
    max_page_size = 100
