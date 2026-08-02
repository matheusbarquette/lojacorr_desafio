import re
from django.db import models
from .validators import validar_cnpj

# Unidades federativas do Brasil, usadas como choices no campo `uf`
UF_CHOICES = [
    ('AC', 'Acre'), ('AL', 'Alagoas'), ('AP', 'Amapá'), ('AM', 'Amazonas'),
    ('BA', 'Bahia'), ('CE', 'Ceará'), ('DF', 'Distrito Federal'),
    ('ES', 'Espírito Santo'), ('GO', 'Goiás'), ('MA', 'Maranhão'),
    ('MT', 'Mato Grosso'), ('MS', 'Mato Grosso do Sul'), ('MG', 'Minas Gerais'),
    ('PA', 'Pará'), ('PB', 'Paraíba'), ('PR', 'Paraná'),
    ('PE', 'Pernambuco'), ('PI', 'Piauí'), ('RJ', 'Rio de Janeiro'),
    ('RN', 'Rio Grande do Norte'), ('RS', 'Rio Grande do Sul'),
    ('RO', 'Rondônia'), ('RR', 'Roraima'), ('SC', 'Santa Catarina'),
    ('SP', 'São Paulo'), ('SE', 'Sergipe'), ('TO', 'Tocantins'),
]


class Seguradora(models.Model):
    # --- Dados básicos, vindos direto do payload de importação ---
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(
        max_length=14,
        unique=True,
        db_index=True,
        validators=[validar_cnpj],
        help_text='Apenas dígitos, sem formatação (normalizado automaticamente ao salvar).',
    )
    uf = models.CharField(max_length=2, choices=UF_CHOICES, db_index=True)

    # --- Dados de enriquecimento, preenchidos depois via BrasilAPI ---
    nome_fantasia = models.CharField(max_length=255, blank=True, default='')
    situacao_cadastral = models.CharField(max_length=100, blank=True, default='')

    # `enriquecido_em` vazio = ainda na fila do worker. É esse campo que define
    # o que é "pendente", então não precisamos de uma tabela de fila separada.
    enriquecido_em = models.DateTimeField(blank=True, null=True)

    # Sem esse contador, um CNPJ que a BrasilAPI não conhece ficaria pendente
    # para sempre e seria reconsultado a cada rodada do worker. Depois de N
    # tentativas o registro sai da fila e fica só com os dados básicos.
    tentativas = models.PositiveSmallIntegerField(default=0)

    # --- Metadados ---
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'seguradoras'
        ordering = ['nome']
        verbose_name = 'Seguradora'
        verbose_name_plural = 'Seguradoras'

    def __str__(self) -> str:
        return f'{self.nome} ({self.cnpj})'

    def save(self, *args, **kwargs):
        # garante que o CNPJ salvo é sempre só dígitos, mesmo
        # que o registro seja criado fora da API (admin, shell, outro script).
        if self.cnpj:
            self.cnpj = re.sub(r'\D', '', self.cnpj)
        super().save(*args, **kwargs)
