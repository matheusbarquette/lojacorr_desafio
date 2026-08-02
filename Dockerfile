# Build multi-stage: o estágio `builder` tem o compilador e os headers para
# montar as dependências; o estágio final recebe só o virtualenv pronto. O
# resultado é uma imagem sem toolchain de compilação — menor e com menos
# superfície de ataque.

# --------------------------------------------------------------------------- #
# Estágio 1 — builder
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

# O venv fica em /opt/venv para ser copiado inteiro no próximo estágio.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiar só os requirements antes do código faz o Docker guardar a camada de
# dependências em cache: mudar o código-fonte não reinstala nada.
#
# As dependências de teste entram na imagem de propósito, para que o avaliador
# rode a suíte com um comando só (`docker compose run --rm web pytest`) sem
# precisar de Python instalado na máquina. São ~15 MB; o que o multi-stage corta
# de verdade é o build-essential, que fica só neste estágio.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip && pip install -r requirements-dev.txt

# --------------------------------------------------------------------------- #
# Estágio 2 — runtime
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # /app não é gravável pelo usuário da aplicação; sem isso o pytest emitiria
    # warning ao tentar criar o diretório de cache dele.
    PYTEST_ADDOPTS="-p no:cacheprovider"

# Roda como usuário sem privilégios em vez de root.
RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .

USER app

EXPOSE 8000

# Comando padrão da imagem. As migrations NÃO rodam aqui: quem as aplica é o
# `command` do serviço web no docker-compose.yml, para que todo o passo a passo
# da subida fique visível num arquivo só.
CMD ["gunicorn", "core.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-"]
