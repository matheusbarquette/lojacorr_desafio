import django_filters
from .models import Seguradora


class SeguradoraFilter(django_filters.FilterSet):
    # iexact: UF="sp" e UF="SP" retornam o mesmo resultado
    uf = django_filters.CharFilter(field_name='uf', lookup_expr='iexact')
    # icontains: nome="porto" encontra "Porto Seguro" (busca parcial, case-insensitive)
    nome = django_filters.CharFilter(field_name='nome', lookup_expr='icontains')

    class Meta:
        model = Seguradora
        fields = ['uf', 'nome']