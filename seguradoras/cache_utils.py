import hashlib

from django.core.cache import cache

CHAVE_VERSAO = 'seguradoras:listagem:versao'


def versao_atual() -> int:
    versao = cache.get(CHAVE_VERSAO)
    if versao is None:
        versao = 1
        # timeout=None: a versão é metadado de controle, não conteúdo. Se ela
        # expirasse, chaves antigas voltariam a ser alcançáveis.
        cache.set(CHAVE_VERSAO, versao, timeout=None)
    return int(versao)


def invalidar_listagem() -> None:
    """Chamado depois de qualquer escrita que mude o resultado da listagem."""
    try:
        cache.incr(CHAVE_VERSAO)
    except ValueError:
        # `incr` levanta ValueError se a chave não existe (nunca foi criada ou
        # foi despejada pelo Redis).
        cache.set(CHAVE_VERSAO, versao_atual() + 1, timeout=None)


def chave_listagem(caminho_completo: str) -> str:
    """Chave estável para uma requisição de listagem (path + querystring)."""
    bruto = f'{versao_atual()}:{caminho_completo}'
    return f'seguradoras:listagem:{hashlib.sha256(bruto.encode()).hexdigest()[:32]}'
