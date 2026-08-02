import re

from rest_framework import serializers

from .models import Seguradora
from .validators import validar_cnpj


class SeguradoraSerializer(serializers.ModelSerializer):
    """
    Serializer de LEITURA, usado no GET /api/v1/seguradoras/.
    Expõe também os campos que só existem depois do enriquecimento em
    background (nome_fantasia, situacao_cadastral, enriquecido_em).
    """

    class Meta:
        model = Seguradora
        fields = [
            'id', 'nome', 'cnpj', 'uf',
            'nome_fantasia', 'situacao_cadastral', 'enriquecido_em',
            'criado_em', 'atualizado_em',
        ]


class ImportacaoListSerializer(serializers.ListSerializer):
    """
    Validações que só fazem sentido olhando a LISTA inteira, não item a item.

    Sem a checagem de CNPJ repetido aqui, um payload com o mesmo CNPJ duas vezes
    geraria dois INSERTs para a mesma chave única e o `bulk_create` estouraria
    IntegrityError já dentro do banco.
    """

    def validate(self, itens):
        if not itens:
            raise serializers.ValidationError('Envie ao menos uma seguradora.')

        cnpjs = [item['cnpj'] for item in itens]
        repetidos = sorted({cnpj for cnpj in cnpjs if cnpjs.count(cnpj) > 1})
        if repetidos:
            raise serializers.ValidationError(
                f'CNPJ repetido no mesmo envio: {", ".join(repetidos)}.'
            )
        return itens


class SeguradoraImportSerializer(serializers.ModelSerializer):
    """
    Serializer de ESCRITA, usado no POST /api/v1/seguradoras/importar/ com
    `many=True`. Valida e normaliza um item; quem persiste é `services.py`.
    """

    # Redeclaramos o `cnpj` explicitamente por um motivo importante: gerado
    # automaticamente a partir do model (que tem unique=True), o DRF anexaria um
    # UniqueValidator — e aí toda reimportação de um CNPJ existente viraria erro,
    # justamente o caso que o upsert precisa aceitar.
    cnpj = serializers.CharField(
        max_length=20,
        validators=[validar_cnpj],
        help_text='Com ou sem formatação: "00.000.000/0001-91" ou "00000000000191".',
    )

    class Meta:
        model = Seguradora
        fields = ['nome', 'cnpj', 'uf']
        list_serializer_class = ImportacaoListSerializer

    def to_internal_value(self, data):
        """
        Normaliza ANTES das validações de campo rodarem. É o que garante que
        "00.000.000/0001-91" e "00000000000191" sejam o MESMO CNPJ na hora do
        upsert, e que "sp" e "SP" sejam a mesma UF.
        """
        if isinstance(data, dict):
            data = dict(data)
            if data.get('cnpj') is not None:
                data['cnpj'] = re.sub(r'\D', '', str(data['cnpj']))
            if data.get('uf') is not None:
                data['uf'] = str(data['uf']).strip().upper()
            if data.get('nome') is not None:
                data['nome'] = str(data['nome']).strip()
        return super().to_internal_value(data)


class ResultadoImportacaoSerializer(serializers.Serializer):
    """Só documenta a resposta do POST no Swagger."""

    criadas = serializers.IntegerField()
    atualizadas = serializers.IntegerField()
    total = serializers.IntegerField()
