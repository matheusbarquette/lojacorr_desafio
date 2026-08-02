import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {'1', 'true', 'yes', 'on'}


# --- Segurança -------------------------------------------------------------
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-chave-apenas-para-dev')
DEBUG = env_bool('DJANGO_DEBUG', True)
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '*').split(',')


# --- Apps ------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'django_filters',
    'drf_spectacular',
    'seguradoras',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# --- Banco de dados --------------------------------------------------------
# PostgreSQL sempre, inclusive nos testes. Chegamos a ter um fallback para
# SQLite quando rodando fora do Docker, mas isso significaria validar o código
# num banco diferente do de produção -- e a diferença é real: o `LIKE` do SQLite
# só é case-insensitive para ASCII, então o filtro `?nome=são` NÃO encontraria
# "SÃO PAULO SEGUROS", enquanto no Postgres encontra. O SQLite também ignora o
# `max_length` de VARCHAR, que o Postgres aplica.
#
# Os defaults abaixo (localhost:5433) apontam para o Postgres do docker-compose
# visto de fora do container. É o que permite rodar `pytest` na máquina e ainda
# assim usar o mesmo banco. Dentro do compose, POSTGRES_HOST=db sobrescreve.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB', 'seguradoras'),
        'USER': os.getenv('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5433'),
    }
}


# --- Cache -----------------------------------------------------------------
# Sem REDIS_URL -> cache em memória do processo (dev local e testes).
# Com REDIS_URL -> Redis, que é o que o docker-compose usa.
#
# Por que Redis no Docker: o Gunicorn roda com vários processos e o worker de
# enriquecimento é outro container. Um cache em memória seria uma cópia isolada
# por processo, e a invalidação feita por um não valeria para os outros.
REDIS_URL = os.getenv('REDIS_URL')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

# Por quantos segundos uma página de listagem fica em cache.
CACHE_LISTAGEM_TTL = int(os.getenv('CACHE_LISTAGEM_TTL', '60'))


# --- Django REST Framework -------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'seguradoras.pagination.SeguradoraPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'API de Seguradoras',
    'DESCRIPTION': (
        'Catálogo de seguradoras com importação em lote (upsert por CNPJ) e '
        'enriquecimento de dados em background via BrasilAPI.'
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}


# --- Integração externa ----------------------------------------------------
BRASILAPI_CNPJ_URL = os.getenv('BRASILAPI_CNPJ_URL', 'https://brasilapi.com.br/api/cnpj/v1/{cnpj}')
BRASILAPI_TIMEOUT = float(os.getenv('BRASILAPI_TIMEOUT', '5'))


# --- Logging ---------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'padrao': {'format': '[{asctime}] {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'padrao'},
    },
    'loggers': {
        'seguradoras': {
            'handlers': ['console'],
            'level': os.getenv('LOG_LEVEL', 'INFO'),
        },
    },
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
