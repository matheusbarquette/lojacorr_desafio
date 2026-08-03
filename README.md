# API de Seguradoras

API REST para gerenciar um catálogo de seguradoras, com importação em lote
(upsert por CNPJ) e enriquecimento de dados em background via
[BrasilAPI](https://brasilapi.com.br).

**Stack:** Python 3.12 · Django 5.1 · Django REST Framework · PostgreSQL · Redis · Docker

---

## Subindo o ambiente

Pré-requisito: Docker com Compose v2. Um comando:

```bash
docker compose up --build
```

Sobe quatro serviços, aplica as migrations sozinho e a API fica em
`http://localhost:8000`:

| Serviço  | Papel |
|----------|-------|
| `db`     | PostgreSQL 16 |
| `redis`  | cache da listagem, compartilhado entre `web` e `worker` |
| `web`    | a API (Gunicorn). Aplica as migrations ao subir |
| `worker` | enriquecimento em background, em laço a cada 15s |

Não é preciso criar `.env` — todos os valores têm padrão. O `.env.example`
lista o que dá para ajustar.

Endereços úteis:

- `http://localhost:8000/api/docs/` — **Swagger interativo**
- `http://localhost:8000/api/v1/seguradoras/` — listagem
- `http://localhost:8000/health/` — healthcheck
- `http://localhost:8000/admin/` — Django admin (crie um usuário com
  `docker compose exec web python manage.py createsuperuser`)

## Rodando os testes

```bash
docker compose run --rm web pytest
```

São 62 testes e **nenhum deles acessa a internet**: a URL da BrasilAPI aponta
para um host inexistente e as chamadas HTTP são interceptadas pelo `respx`. Se
algum código tentar sair para a rede, o teste quebra em vez de ficar lento e
instável.

A suíte roda contra **PostgreSQL**, o mesmo banco de produção — não contra
SQLite. Isso é proposital, veja [Por que só PostgreSQL](#por-que-só-postgresql).

<details>
<summary>Rodando fora do container</summary>

Com a stack de pé (o Postgres fica exposto em `localhost:5433`):

```bash
python -m venv venv && venv\Scripts\activate     # Linux/macOS: source venv/bin/activate
pip install -r requirements-dev.txt
pytest                    # usa o Postgres do compose
python manage.py runserver
```

Os defaults de `POSTGRES_HOST`/`POSTGRES_PORT` já apontam para `localhost:5433`,
então não é preciso configurar nada — só ter o `docker compose up` rodando.

</details>

## Acessando o banco

O PostgreSQL fica exposto na máquina, para uso com Beekeeper Studio, DBeaver,
pgAdmin ou `psql`:

| Campo | Valor |
|-------|-------|
| Host | `localhost` |
| Porta | `5433` |
| Database | `seguradoras` |
| Usuário | `postgres` |
| Senha | `postgres` |

```bash
psql -h localhost -p 5433 -U postgres -d seguradoras
```

A porta externa é **5433**, e não 5432, para não conflitar com um PostgreSQL já
instalado na máquina. Dá para mudar com `POSTGRES_PORT_EXTERNA` no `.env`. A
tabela do catálogo se chama `seguradoras`.

---

## Endpoints

### `POST /api/v1/seguradoras/importar/`

Recebe uma **lista** de seguradoras, grava os dados básicos e responde na hora.

Payload de exemplo (está no repositório como `exemplo-payload.json`):

```json
[
  {"nome": "Porto Seguro",     "cnpj": "61.198.164/0001-60", "uf": "sp"},
  {"nome": "Bradesco Seguros", "cnpj": "92682038000100",     "uf": "RJ"}
]
```

Enviando o arquivo — funciona igual em **bash, cmd e PowerShell**:

```bash
curl -X POST http://localhost:8000/api/v1/seguradoras/importar/ -H "Content-Type: application/json" -d @exemplo-payload.json
```

Resposta:

```json
{ "criadas": 2, "atualizadas": 0, "total": 2 }
```

O CNPJ é aceito **com ou sem formatação** e gravado só com dígitos; a UF é
normalizada para maiúscula. Ou seja, `"61.198.164/0001-60"` e
`"61198164000160"` são o mesmo registro na hora do upsert.

Reenviar um CNPJ que já existe **atualiza** em vez de duplicar:

```json
{ "criadas": 0, "atualizadas": 1, "total": 1 }
```

**Validação é tudo-ou-nada:** se qualquer item do lote for inválido (CNPJ com
dígito verificador errado, UF inexistente, CNPJ repetido dentro do mesmo envio),
a resposta é `400` e **nada** é gravado. O erro vem por posição da lista:

```json
[ {}, { "cnpj": ["CNPJ inválido (dígito verificador não confere)."] } ]
```

### `GET /api/v1/seguradoras/`

Listagem paginada, com filtros por UF e nome.

| Parâmetro   | Efeito |
|-------------|--------|
| `uf`        | filtra por UF, ignorando maiúsculas (`?uf=sp`) |
| `nome`      | busca parcial, ignorando maiúsculas (`?nome=porto`) |
| `page`      | página (padrão 20 itens) |
| `page_size` | itens por página, até o teto de 100 |

```bash
curl "http://localhost:8000/api/v1/seguradoras/?uf=SP&nome=porto&page_size=10"
```

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "nome": "Porto Seguro",
      "cnpj": "61198164000160",
      "uf": "SP",
      "nome_fantasia": "PORTO SEGURO COMPANHIA DE SEGUROS GERAIS",
      "situacao_cadastral": "ATIVA",
      "enriquecido_em": "2026-08-02T13:16:28.798000-03:00",
      "criado_em": "2026-08-02T13:15:02.101000-03:00",
      "atualizado_em": "2026-08-02T13:16:28.798000-03:00"
    }
  ]
}
```

A resposta traz o header `X-Cache: HIT|MISS`, indicando se veio do cache ou do
banco.

Logo depois da importação, `nome_fantasia` e `situacao_cadastral` vêm vazios e
`enriquecido_em` vem `null` — o worker preenche em segundos.

---

## Estratégia para desacoplar a chamada da API externa

**O problema:** o `POST /importar/` precisa responder rápido, mas o
enriquecimento depende de uma API externa que pode estar lenta ou fora do ar. Se
a consulta acontecesse dentro do request, um lote de 50 CNPJs viraria 50
chamadas HTTP sequenciais antes de responder — e um timeout da BrasilAPI
derrubaria a importação inteira.

**A solução escolhida: management command rodando em laço, em um container
separado.**

```
POST /importar/  ──▶  grava os dados básicos  ──▶  responde 201
                              │
                              │  (o registro nasce com enriquecido_em = NULL)
                              ▼
                       ┌─────────────┐
                       │  container  │  a cada 15s: pega quem está pendente,
                       │   worker    │  consulta a BrasilAPI, preenche os campos
                       └─────────────┘
```

A view **não sabe** que o enriquecimento existe. Ela só grava e responde. O
worker (`python manage.py enriquecer_seguradoras --loop`) varre os registros com
`enriquecido_em IS NULL` e os atualiza.

**Por que não uma Thread disparada no `save()`** (a outra alternativa sugerida
no enunciado):

- Uma thread morre junto com o processo. Se o container reiniciar no meio de um
  lote, aqueles registros ficam pendentes para sempre — ninguém volta neles.
- O worker é o oposto: como o critério de "pendente" está **no banco** e não na
  memória, reiniciar o worker (ou subir dois) não perde trabalho. O que não foi
  processado continua na fila.
- A thread também competiria por conexão de banco com o Gunicorn, e o número de
  threads cresceria junto com o volume de importações, sem controle.

O custo dessa escolha é a latência: o dado leva até 15s para aparecer, em vez de
"quase imediato". Para um catálogo, é uma troca claramente boa.

**Não precisa de fila.** O campo `enriquecido_em` já é a fila: `NULL` = pendente,
preenchido = concluído. Sem Celery, sem RabbitMQ, sem tabela extra.

### Tratamento de erro

O tipo da falha decide o que acontece com o registro:

| Situação | Exceção | O que o worker faz |
|----------|---------|--------------------|
| BrasilAPI não conhece o CNPJ (404) | `CNPJNaoEncontrado` | tira da fila na hora — reconsultar amanhã não vai fazer o CNPJ passar a existir |
| Rate limit (429) | `LimiteDeRequisicoesExcedido` | **encerra a rodada** e não penaliza ninguém |
| Timeout, rede, 5xx | `ServicoIndisponivel` | incrementa `tentativas` e volta na próxima rodada, até 3 vezes |
| Erro inesperado (bug) | qualquer uma | logado com stacktrace e contado como falha; o worker segue para o próximo |

Em **todos** os casos o registro continua com os dados básicos e o sistema não
trava, como o desafio pede. O limite de 3 tentativas existe para que um CNPJ
problemático não seja reconsultado a cada 15s para sempre.

**Sobre o 429**, que é o caso menos óbvio: importando 50 registros de uma vez, a
BrasilAPI passou a recusar depois de ~30 consultas (medi ~2,4 req/s). O
tratamento ingênuo — contar como falha transitória qualquer — tem dois defeitos:

1. o worker continuaria consultando os 20 restantes, empilhando mais 429 contra
   uma API que acabou de pedir para desacelerar;
2. cada um deles gastaria uma das 3 tentativas. **Duas rodadas de rate limit e
   registros perfeitamente válidos seriam descartados de vez** — por um limite
   temporário que não tinha nada a ver com eles.

Por isso o 429 tem exceção própria: a rodada para no primeiro, e ninguém tem
`tentativas` incrementado. A fila volta inteira 15s depois, quando a janela do
limite já passou. Se quiser reduzir a chance de bater no limite, é só usar um
`--tamanho-lote` menor — 20 registros a cada 15s dá ~1,3 req/s.

---

## Decisões de projeto

**Upsert em lote com número fixo de queries.** A importação custa no máximo 3
queries — 1 `SELECT` para descobrir quais CNPJs já existem, 1 `bulk_create` e 1
`bulk_update` — independente de o lote ter 1 ou 500 itens. A alternativa ingênua
(`get_or_create` num laço) seria 2 a 3 queries **por item**. Há um teste que
importa 1 item e 5 itens e verifica que o custo é o mesmo, para que a regressão
apareça na suíte e não em produção.

**O upsert atualiza só `nome` e `uf`.** Reimportar o cadastro básico não pode
apagar `nome_fantasia` e `situacao_cadastral`, que são resultado do trabalho do
worker.

**Cache invalidado por versionamento de chave.** A listagem tem combinações
abertas de filtro e página (`?uf=SP`, `?uf=SP&page=2`, `?nome=porto`...), então
não dá para enumerar as chaves e apagá-las uma a uma. Toda chave embute um
número de versão; escrever no catálogo incrementa esse número e todas as chaves
antigas ficam inalcançáveis de uma vez, numa operação só. As entradas órfãs
expiram sozinhas pelo TTL. É por isso que o cache é o **Redis** e não memória do
processo: o Gunicorn roda com vários workers e o enriquecimento é outro
container — todos precisam enxergar a mesma versão.

**Cliente HTTP isolado atrás de uma interface.** `integrations/brasilapi.py` só
fala HTTP e devolve um `DadosCNPJ` ou levanta exceção tipada; não conhece ORM
nem serializer. A regra de enriquecimento depende do `Protocol ClienteCNPJ`, não
da classe concreta — o que permite injetar um duplo nos testes da regra e trocar
de provedor sem tocar no negócio.

**Sem retry interno no cliente.** Erro transitório já é naturalmente
reprocessado na rodada seguinte do worker. Um retry com `sleep` dentro da
consulta só prenderia a thread duplicando o que o laço já faz.
