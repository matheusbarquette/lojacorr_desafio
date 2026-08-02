from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .cache_utils import chave_listagem
from .filters import SeguradoraFilter
from .models import Seguradora
from .serializers import (
    ResultadoImportacaoSerializer,
    SeguradoraImportSerializer,
    SeguradoraSerializer,
)
from .services import importar_em_lote


@extend_schema(exclude=True)
def health(_request):
    """Usado pelo healthcheck do docker-compose: a API só está pronta com o banco de pé."""
    try:
        connection.ensure_connection()
    except Exception as exc:
        return JsonResponse({'status': 'erro', 'banco': str(exc)}, status=503)
    return JsonResponse({'status': 'ok'})


class SeguradoraViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnlyModelViewSet dá `list` e `retrieve` prontos. Não expomos
    create/update/delete genéricos: a escrita acontece só pela ação `importar`,
    que tem regra própria (upsert em lote).
    """

    queryset = Seguradora.objects.all()
    serializer_class = SeguradoraSerializer
    filterset_class = SeguradoraFilter

    @extend_schema(
        summary='Lista seguradoras',
        description=(
            'Listagem paginada com filtros por UF e nome. A resposta é cacheada e '
            'invalidada automaticamente a cada escrita no catálogo. O header '
            'X-Cache indica se veio do cache (HIT) ou do banco (MISS).'
        ),
        parameters=[
            OpenApiParameter('uf', str, description='Sigla da UF (ex.: SP). Ignora maiúsculas.'),
            OpenApiParameter('nome', str, description='Busca parcial pelo nome.'),
        ],
    )
    def list(self, request, *args, **kwargs):
        # A chave inclui a querystring inteira, então cada combinação de filtro
        # e página tem sua própria entrada de cache.
        chave = chave_listagem(request.get_full_path())

        conteudo = cache.get(chave)
        if conteudo is None:
            conteudo = super().list(request, *args, **kwargs).data
            cache.set(chave, conteudo, timeout=settings.CACHE_LISTAGEM_TTL)
            origem = 'MISS'
        else:
            origem = 'HIT'

        resposta = Response(conteudo)
        resposta['X-Cache'] = origem
        return resposta

    @extend_schema(
        summary='Importa seguradoras em lote',
        description=(
            'Salva os dados básicos imediatamente (upsert por CNPJ) e responde na hora. '
            'O enriquecimento via BrasilAPI acontece FORA deste request, no worker '
            '`enriquecer_seguradoras`. Se qualquer item for inválido, o lote inteiro '
            'é rejeitado com 400 e nada é gravado.'
        ),
        request=SeguradoraImportSerializer(many=True),
        responses={201: ResultadoImportacaoSerializer},
    )
    @action(detail=False, methods=['post'], url_path='importar')
    def importar(self, request):
        entrada = SeguradoraImportSerializer(data=request.data, many=True)
        entrada.is_valid(raise_exception=True)

        resultado = importar_em_lote(entrada.validated_data)

        return Response(resultado, status=status.HTTP_201_CREATED)
