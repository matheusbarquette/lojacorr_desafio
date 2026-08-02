from django.contrib import admin
from .models import Seguradora


@admin.register(Seguradora)
class SeguradoraAdmin(admin.ModelAdmin):
    list_display = ['nome', 'cnpj', 'uf', 'nome_fantasia', 'situacao_cadastral', 'enriquecido_em']
    list_filter = ['uf', 'situacao_cadastral']
    search_fields = ['nome', 'cnpj', 'nome_fantasia']
