class ErroIntegracao(Exception):
    """Base de tudo que pode dar errado ao falar com a API externa."""


class CNPJNaoEncontrado(ErroIntegracao):
    """404 — a BrasilAPI não conhece esse CNPJ. Retentar só gasta quota."""

    def __init__(self, cnpj: str):
        super().__init__(f'CNPJ {cnpj} não encontrado na BrasilAPI.')
        self.cnpj = cnpj


class ServicoIndisponivel(ErroIntegracao):
    """Timeout, falha de rede ou erro do servidor. Vale tentar de novo depois."""


class LimiteDeRequisicoesExcedido(ServicoIndisponivel):
    """
    429 — a API pediu para desacelerar - Rate Limit.
    """
