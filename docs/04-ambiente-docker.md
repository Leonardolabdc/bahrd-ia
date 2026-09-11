# POC IA — Central de Monitoramento Bahrd · Ambiente Docker

> **Versão:** 1.0 · **Data:** 11/08/2026
> **Relacionados:** 01 · Fluxo · [02 · Plano](02-plano-execucao-backend.md) · 03 · Checklist · 03 · Prompts
> **Implementa:** decisão D7 (Docker primeiro, OCI depois) e a seção 3.4 do plano de execução

---

## 1. Como subir

Pré-requisito único: Docker Desktop instalado. Nada de nuvem, nada de VPN.

```powershell
.\dev.ps1 setup      # cria o .env a partir do template
.\dev.ps1 up         # sobe a pilha
.\dev.ps1 migrate    # cria o usuário do Oracle e aplica as migrações
.\dev.ps1 saude      # confirma que API, Oracle, MySQL e Redis conversam
```

Em Linux ou macOS os mesmos alvos existem no `Makefile` (`make setup`, `make up`,
`make migrate`). Quem preferir o comando direto:

```powershell
Copy-Item .env.example .env
docker compose up -d
docker compose run --rm migrate
```

**O primeiro `up` demora**, entre 5 e 15 minutos: a imagem do Oracle tem
alguns GB e o primeiro boot cria o banco. Do segundo em diante são segundos.

### Endereços locais

| Serviço | Endereço |
|---|---|
| API (docs, saúde) | http://localhost:8000/docs · http://localhost:8000/saude/pronto |
| Painel do operador | http://localhost:5173 |
| Jaeger (traces) | http://localhost:16686 |
| MinIO (console) | http://localhost:9001 |
| Oracle | `localhost:1521/FREEPDB1` |
| MySQL | `localhost:3306` |
| Redis | `localhost:6379` |

As portas ficam presas em `127.0.0.1`: banco de desenvolvimento não vai para a
rede local.

---

## 2. O que sobe

| Serviço | Imagem | Papel | Vira o quê na OCI |
|---|---|---|---|
| `oracle` | `container-registry.oracle.com/database/free:latest` | Sistema de registro (23ai: `VECTOR` + `BLOCKCHAIN TABLE`) | Autonomous Database Serverless 23ai |
| `mysql` | `mysql:8.4` | Camada operacional (conversas, mensagens, métricas) | MySQL HeatWave Database Service |
| `redis` | `redis:7-alpine` | Barramento (Streams) + cache/locks, AOF ligado | OCI Cache (Redis 7) |
| `minio` | `minio/minio` | Object storage de áudio, API S3 | OCI Object Storage (**também API S3**) |
| `otel` | `jaegertracing/jaeger:2.11.0` | Coletor OTLP + UI de traces | OCI APM |
| `api` | build local | `api-gateway` (FastAPI) | OKE ou VM Compute |
| `worker` | build local, **mesma imagem** | Workers arq | OKE ou VM Compute |
| `web` | build local | Painel do operador (Vite dev server) | Estático no nginx atrás do OCI LB |
| `migrate` | build local, **mesma imagem** | Migrações; perfil `ferramentas` | Job no pipeline de deploy |
| `shell` | build local, **mesma imagem** | `bash` dentro da imagem real; perfil `ferramentas` | — |

`api`, `worker`, `migrate` e `shell` são **a mesma imagem**. Muda o comando,
nunca a imagem — princípio 10.

---

## 3. As decisões que não são óbvias

### 3.1 O comentário no `.env` só vale em linha própria

O `--env-file` do Docker não corta comentário no fim da linha. Escrever

```dotenv
APP_ENV=dev                  # dev | hml | prd-poc
```

faz o valor virar a string literal `dev                  # dev | hml | prd-poc`,
e a validação do Pydantic recusa. Por isso o `.env.example` traz todo comentário
acima da variável. Isso apareceu no primeiro teste do ambiente, não em teoria.

### 3.2 `/saude/vivo` não toca banco — `/saude/pronto` toca

São coisas diferentes e confundi-las derruba o serviço em produção:

- **`/saude/vivo`** (*liveness*) responde enquanto o processo está sadio. Se o
  Oracle cair, matar e recriar o container não resolve nada e só piora a
  indisponibilidade — por isso esta sonda não olha dependência nenhuma.
- **`/saude/pronto`** (*readiness*) verifica Oracle, MySQL e Redis e devolve
  503 enquanto alguma estiver fora. O balanceador para de mandar tráfego, sem
  reiniciar o processo.

Pelo mesmo motivo o `api` depende do Oracle com `condition: service_started`, e
não `service_healthy`: o banco leva minutos no primeiro boot e a API não precisa
dele para subir.

### 3.3 O schema é criado sem privilégio de DBA, desde o notebook

É a contramedida à **armadilha 1** do plano: o Oracle Free em container é
permissivo (você é DBA, `ALTER SYSTEM` funciona) e o ADB-S não é. Um DDL escrito
com liberdade de DBA descobre isso no fim do projeto, no pior momento.

Então: `migrations/oracle/bootstrap_local.py` cria o usuário `CENTRAL_IA` com o
conjunto mínimo de privilégios que o ADB-S também concede — e nada mais. Todo o
schema é criado como esse usuário. O bootstrap **recusa rodar** com `APP_ENV`
diferente de `dev`, porque na nuvem esse passo é da TI.

### 3.4 Duas diferenças conscientes entre local e ADB-S

Estão isoladas em *placeholders* que o runner resolve pelo ambiente, para que o
resto do DDL seja byte a byte o mesmo:

| Placeholder | Local | ADB-S | Por quê |
|---|---|---|---|
| `${AUDITORIA_DIAS_IDLE}` | `0` | `31` | A `BLOCKCHAIN TABLE` com 31 dias não pode ser derrubada — em dev isso impede recriar o schema |
| `${TIPO_INDICE_VETORIAL}` | `NEIGHBOR PARTITIONS` (IVF) | `INMEMORY NEIGHBOR GRAPH` (HNSW) | HNSW exige `vector_memory_size`, que só se ajusta com `ALTER SYSTEM` — privilégio que a aplicação não tem por decisão |

A consulta com pré-filtro do RAG é idêntica nos dois casos.

### 3.5 Duas correções no DDL do plano

Ambas apareceram ao rodar as migrações de verdade, não na leitura.

**MySQL — `mensagem` não podia ser particionada.** O plano (§5.2) traz
`PRIMARY KEY (mensagem_id)` junto com `PARTITION BY RANGE (TO_DAYS(criada_em))`.
O MySQL recusa com o erro 1503: toda coluna de particionamento precisa fazer
parte de cada chave única da tabela. A migração `0001` usa
`PRIMARY KEY (mensagem_id, criada_em)`. O particionamento existe para o expurgo
de 90 dias, então vale manter e corrigir a chave.

**Oracle — a auditoria não podia usar `TIMESTAMP WITH TIME ZONE`.** O plano
(§5.1) declara `momento TIMESTAMP WITH TIME ZONE` na `BLOCKCHAIN TABLE`, e o
Oracle recusa com ORA-05730: esse tipo não é suportado em blockchain table.
A coluna virou `TIMESTAMP` puro, gravado sempre em UTC via
`SYS_EXTRACT_UTC(SYSTIMESTAMP)`.

A troca é mais do que sintática, e para melhor: a trilha de auditoria deixa de
depender do fuso da sessão que escreveu. Quem lê a auditoria — inclusive numa
reconstrução meses depois — passa a ter um único referencial.

### 3.6 DDL no Oracle não tem rollback

O Oracle faz *commit* implícito a cada DDL. Se uma migração falhar no meio, as
tabelas criadas até ali **permanecem** e o script não fica marcado como
aplicado — rodar de novo dá ORA-00955 (objeto já existe).

Não há como o runner contornar isso: é comportamento do banco. O que existe é
processo:

- **Em dev**, o caminho é `.\dev.ps1 reset` (apaga os volumes) ou derrubar o
  usuário: `DROP USER CENTRAL_IA CASCADE` como SYS e rodar `migrate` de novo.
- **Em hml e prd-poc**, é exatamente por isso que existe o **deploy de fumaça
  do Sprint 3**: a migração roda contra um ADB-S descartável antes de tocar
  qualquer ambiente que importe.

### 3.7 Voz não roda em Docker local

**Armadilha 3** do plano. SIP e WebRTC precisam de IP alcançável e faixa UDP
aberta; em notebook atrás de NAT doméstico, com o GoTo em nuvem, isso falha de
formas confusas e consome dias de depuração no lugar errado.

Por isso não existe serviço de voz no compose. `MODO_VOZ=voz_simulada` injeta um
WAV como se fosse a fala do cliente e grava a resposta do TTS em arquivo — o que
cobre toda a lógica de conversa, playbook, ferramentas e guardrails, que é 90%
do trabalho. A pilha real (`voz_livekit_sip`) sobe separada, numa VM com IP
público, no Sprint 3.

### 3.8 O front-end não embute o endereço da API

O bundle lê `window.__CONFIG__`, escrito em `/config.js` pelo entrypoint do
nginx a partir do ambiente. É o que faz "uma imagem, todos os ambientes" valer
também para o painel: a mesma imagem do OCIR serve `hml` e `prd-poc` apontando
para APIs diferentes.

---

## 4. Migrações

Duas trilhas, uma ferramenta cada:

**Oracle** — SQL numerado + runner próprio. Sem Alembic: `BLOCKCHAIN TABLE`,
`VECTOR` e os tipos do 23ai não sobrevivem ao *autogenerate*.

```powershell
docker compose run --rm shell -lc "python -m migrations.oracle.runner --status"
docker compose run --rm shell -lc "python -m migrations.oracle.runner"
```

O runner grava o SHA-256 de cada script aplicado. Editar um script já aplicado
falha na execução seguinte — migração é *append-only*, o certo é criar o
próximo número.

**MySQL** — Alembic. A URL vem de `Settings`, nunca do `alembic.ini`.

```powershell
docker compose run --rm shell -lc "alembic upgrade head"
docker compose run --rm shell -lc "alembic revision -m 'descricao'"
```

`.\dev.ps1 migrate` roda o bootstrap e as duas trilhas em sequência.

---

## 5. Matriz de paridade — o que muda no deploy

| Componente | Local | OCI | Como isolamos |
|---|---|---|---|
| Oracle | Free 23ai em container | ADB-S 23ai | `ORACLE_WALLET_DIR` vazio ou preenchido — nenhum DDL depende de DBA |
| MySQL | `mysql:8.4` | MySQL HeatWave DS | `MYSQL_SSL_MODE`; o caminho TLS já existe no código |
| Redis | `redis:7-alpine` | OCI Cache | endpoint + `REDIS_AUTH_TOKEN` |
| Object storage | MinIO | OCI Object Storage | mesmo cliente boto3 — **paridade real** |
| Segredos | `.env` | OCI Vault | interface `SecretProvider`, duas implementações |
| Observabilidade | Jaeger | OCI APM | OpenTelemetry nos dois; muda o exportador |
| TLS | não termina | OCI LB + WAF | a aplicação nunca termina TLS |
| Identidade | credencial em env | *instance principal* | `SecretProvider` + cliente de storage |
| **Voz** | ⚠️ sem paridade | GoTo ↔ LiveKit em VM | dois modos desde o começo (§3.6) |

---

## 6. Marcos de mitigação de risco

| Sprint | O que | Por que agora |
|---|---|---|
| **1** | Publicar a primeira imagem no OCIR | Descobre problema de registry e credencial cedo, quando é barato |
| **3** | **Deploy de fumaça no ADB-S** — só o banco, com todas as migrações e a suíte de integração | Mata a armadilha 1 com 3 sprints de folga |
| **4** | Ambiente `hml` completo na OCI, em paralelo ao local | O piloto assistido do Sprint 5 já acontece na nuvem |
| **5** | Piloto assistido em `prd-poc` | A migração já foi validada — não é surpresa |

O runner do Oracle e o Alembic são exatamente as ferramentas do marco do
Sprint 3: apontar `ORACLE_DSN` e `ORACLE_WALLET_DIR` para o ADB-S e rodar.

---

## 7. Problemas conhecidos

| Sintoma | Causa | O que fazer |
|---|---|---|
| Oracle nunca fica *healthy* | Primeiro boot cria o banco | Esperar. `docker compose logs -f oracle` mostra o progresso; o `start_period` é de 5 min |
| Oracle falha em Mac com chip M | A imagem é x86-64 | Rodar sob emulação (lento) ou apontar `ORACLE_DSN` para uma instância remota — checklist §2 |
| `/saude/pronto` devolve 503 | Alguma dependência fora | O JSON diz qual. Se for Oracle, provavelmente ainda está subindo |
| `migrate` falha com ORA-01017 | Usuário existe com outra senha | `.\dev.ps1 migrate` sincroniza a senha; se não resolver, `.\dev.ps1 reset` |
| Migração do Oracle acusa SHA diferente | Script já aplicado foi editado | Reverter a edição e criar o script seguinte — migração é *append-only* |
| Migração do Oracle falhou no meio; ao repetir dá ORA-00955 | DDL no Oracle não tem rollback (§3.6) | `.\dev.ps1 reset`, ou `DROP USER CENTRAL_IA CASCADE` como SYS e repetir `migrate` |
| Painel não carrega dados | `VITE_API_BASE_URL` aponta para dentro da rede do compose | Em dev o browser está no host: use `http://localhost:8000` |
| Porta ocupada ao subir | Já existe MySQL/Redis/Oracle local | Parar o serviço local ou ajustar o mapeamento no `docker-compose.yml` |

---

## 8. O que ainda não existe

Este documento cobre o **Sprint 0** — a fundação. Ainda não foram escritos:

- **Webhooks** (`/webhooks/rastreamento`, `/webhooks/whatsapp`) — Sprint 1
- **Motor de políticas** (`policy/`) e máquina de estados (`orchestration/`) — Sprints 1 e 2
- **`agent-core`**: montagem de prompt, *tool runner*, guardrails — Sprint 2
- **`voice-agent`** e a pilha LiveKit ↔ GoTo — Sprint 3, na VM
- **`infra/terraform/`** — escrito em paralelo, aplicado quando a conta OCI estiver pronta

O **painel já existe** (`web/`), com as quatro telas do protótipo servidas pela
API. O que ainda não existe é a **origem real dos dados**: `/painel/*` responde
de `central_ia/api/amostra.py`, não do banco. Como o contrato
(`esquemas_painel.py`) é o final, o Sprint 2 troca o corpo das funções em
`rotas/painel.py` e o front-end não muda.
