import time
from django.core.management.base import BaseCommand
from seguradoras.enriquecer import enriquecer_pendentes
from seguradoras.integrations.brasilapi import BrasilAPIClient


class Command(BaseCommand):
    help = 'Enriquece seguradoras pendentes (nome_fantasia, situacao_cadastral) via BrasilAPI.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tamanho-lote', type=int, default=50,
            help='Quantos registros processar por rodada (padrão: 50).',
        )
        parser.add_argument(
            '--loop', action='store_true',
            help='Fica rodando e verificando a fila. É o modo usado pelo container worker.',
        )
        parser.add_argument(
            '--intervalo', type=int, default=15,
            help='Segundos entre as rodadas no modo --loop (padrão: 15).',
        )

    def handle(self, *args, **opcoes):
        tamanho_lote = opcoes['tamanho_lote']
        em_loop = opcoes['loop']
        intervalo = opcoes['intervalo']

        # Um cliente só para toda a execução: o pool de conexões HTTP é
        # reaproveitado entre os CNPJs em vez de reabrir conexão a cada um.
        with BrasilAPIClient() as cliente:
            if not em_loop:
                # Execução avulsa: sempre reporta, nem que seja zero. Sem isso
                # quem rodou na mão não saberia se o comando funcionou.
                self._reportar(self._processar_fila(cliente, tamanho_lote))
                return

            self.stdout.write(self.style.SUCCESS(
                f'Worker iniciado (verificando a fila a cada {intervalo}s). Ctrl+C para parar.'
            ))
            try:
                while True:
                    resultado = self._processar_fila(cliente, tamanho_lote)

                    # No laço a fila está vazia quase o tempo todo. Reportar
                    # rodada vazia encheria o log com milhares de linhas
                    # "0, 0, 0" por dia e esconderia as que importam.
                    if any(resultado.values()):
                        self._reportar(resultado)

                    time.sleep(intervalo)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('\nWorker encerrado.'))

    def _processar_fila(self, cliente, tamanho_lote: int) -> dict:
        return enriquecer_pendentes(cliente, tamanho_lote=tamanho_lote)

    def _reportar(self, resultado: dict) -> None:
        self.stdout.write(
            f'{resultado["enriquecidas"]} enriquecida(s), '
            f'{resultado["nao_encontradas"]} não encontrada(s), '
            f'{resultado["falhas"]} falha(s).'
        )
