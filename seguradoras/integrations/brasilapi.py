import logging
from dataclasses import dataclass
from typing import Protocol
import httpx
from django.conf import settings
from .exceptions import (
    CNPJNaoEncontrado,
    LimiteDeRequisicoesExcedido,
    ServicoIndisponivel,
)

logger = logging.getLogger('seguradoras')


@dataclass(frozen=True, slots=True)
class DadosCNPJ:
    """Só os campos que o catálogo usa — não deixamos o JSON cru da API vazar."""

    nome_fantasia: str
    situacao_cadastral: str

    @classmethod
    def de_payload(cls, payload: dict) -> 'DadosCNPJ':
        # Muitas empresas não têm nome fantasia cadastrado; a razão social é o
        # preenchimento razoável para um catálogo.
        nome_fantasia = (payload.get('nome_fantasia') or payload.get('razao_social') or '').strip()
        situacao = (payload.get('descricao_situacao_cadastral') or '').strip()

        # Os cortes respeitam o max_length das colunas: sem eles, uma razão
        # social muito longa estouraria no INSERT do Postgres.
        return cls(nome_fantasia=nome_fantasia[:255], situacao_cadastral=situacao[:100])


class ClienteCNPJ(Protocol):
    """
    Contrato do que o serviço de enriquecimento precisa.

    Depender desta interface, e não da classe concreta, permite injetar um duplo
    nos testes do serviço e trocar de provedor (BrasilAPI, ReceitaWS...) sem
    tocar na regra de negócio.
    """

    def consultar(self, cnpj: str) -> DadosCNPJ: ...


class BrasilAPIClient:
    """
    Implementação HTTP do `ClienteCNPJ`.

    Usa um único `httpx.Client` por instância, então o pool de conexões é
    reaproveitado entre os CNPJs de uma mesma rodada (evita refazer handshake
    TCP/TLS a cada consulta). Por isso a instância é criada uma vez por execução
    do worker, e não uma por registro.
    """

    def __init__(self, *, url_template: str | None = None, timeout: float | None = None):
        self.url_template = url_template or settings.BRASILAPI_CNPJ_URL
        self.timeout = timeout if timeout is not None else settings.BRASILAPI_TIMEOUT
        self._client = httpx.Client(timeout=self.timeout)

    def consultar(self, cnpj: str) -> DadosCNPJ:
        """
        Consulta um CNPJ.

        Levanta `CNPJNaoEncontrado` (definitivo) ou `ServicoIndisponivel`
        (transitório). Não faz retry interno de propósito: o worker já roda em
        laço, então um erro transitório é naturalmente reprocessado na rodada
        seguinte — sem prender a thread num `sleep`.
        """
        url = self.url_template.format(cnpj=cnpj)

        try:
            resposta = self._client.get(url)
        except httpx.HTTPError as exc:
            # Timeout, DNS, conexão recusada, TLS...
            raise ServicoIndisponivel(f'Falha de rede ao consultar {cnpj}: {exc!r}') from exc

        if resposta.status_code == httpx.codes.NOT_FOUND:
            raise CNPJNaoEncontrado(cnpj)

        if resposta.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise LimiteDeRequisicoesExcedido(
                f'BrasilAPI recusou por excesso de requisições (CNPJ {cnpj}).'
            )

        if resposta.status_code != httpx.codes.OK:
            raise ServicoIndisponivel(f'BrasilAPI respondeu {resposta.status_code} para {cnpj}.')

        try:
            payload = resposta.json()
        except ValueError as exc:
            raise ServicoIndisponivel(f'Corpo não-JSON na resposta para {cnpj}.') from exc

        return DadosCNPJ.de_payload(payload)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> 'BrasilAPIClient':
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()
