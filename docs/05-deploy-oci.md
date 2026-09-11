# POC IA — Central de Monitoramento Bahrd · Caminho do deploy na OCI

> **Versão:** 1.0 · **Data:** 11/08/2026
> **Relacionados:** [02 · Plano](02-plano-execucao-backend.md) · 03 · Checklist · [04 · Ambiente Docker](04-ambiente-docker.md)
> **Estado:** caminho encaminhado e executável. Nada aqui depende de código novo — depende de a conta da OCI existir.

---

## 1. O princípio que torna isto curto

A imagem que roda no seu notebook **é** a imagem que roda na OCI. Não há build
de produção separado, não há `if ambiente == "dev"` no Dockerfile. O que muda
entre ambientes é apenas:

1. **variáveis de ambiente**, e
2. **de onde vêm os segredos** (`.env` → OCI Vault, uma linha na composição).

Por isso o deploy não é uma reescrita: é publicar a imagem, apontar as
variáveis e rodar as migrações. As três coisas já têm ferramenta pronta.

| O que | Ferramenta | Já existe? |
|---|---|---|
| Publicar imagem | `.\publicar.ps1` / `make publicar` | ✅ |
| Migrar Oracle | `python -m migrations.oracle.runner` | ✅ |
| Migrar MySQL | `alembic upgrade head` | ✅ |
| Trocar origem do segredo | `SECRET_PROVIDER=oci_vault` | Interface ✅ · implementação Sprint 4 |
| Provisionar infra | `infra/terraform/` | Estrutura ✅ · módulos por sprint |

---

## 2. Publicar no OCIR (marco do Sprint 1)

O plano coloca isso no Sprint 1 de propósito: descobrir problema de registry e
credencial custa barato agora e caro no Sprint 5.

**Uma vez, para pegar a credencial:**

1. Console da OCI → perfil → **Auth Tokens** → *Generate Token*. Copie na hora;
   não é possível ver de novo.
2. Anote o **namespace** do tenancy (Console → *Tenancy details* → *Object
   storage namespace*).

```powershell
docker login gru.ocir.io
# Usuário: <namespace>/<seu-usuario-oci>       (ex.: grxxxxxxxxx/voce@bahrd.com.br)
# Senha:   o auth token gerado acima — NÃO a senha da conta
```

Para federação de identidade, o usuário é `<namespace>/oracleidentitycloudservice/<usuario>`.

**A cada publicação:**

```powershell
.\publicar.ps1 -Namespace grxxxxxxxxx
.\publicar.ps1 -Namespace grxxxxxxxxx -Versao 0.2.0 -Regiao vcp
.\publicar.ps1 -Namespace grxxxxxxxxx -SomenteConstruir   # valida sem enviar
```

Constrói e envia `backend` e `web` nos alvos `runtime`, com `--platform
linux/amd64` (a OCI é x86; publicar de um Mac com chip M sem isso gera imagem
ARM que não sobe).

> **Aponte o deploy para a etiqueta com versão, nunca para `:latest`.** Sem
> isso não existe rollback determinístico — e num piloto assistido, voltar
> rápido vale mais do que subir rápido.

---

## 3. Deploy de fumaça no ADB-S (marco do Sprint 3)

O passo que **mata a armadilha 1** — "funcionou no Oracle Free, quebrou no
Autonomous" — com três sprints de folga. Provisiona-se **só o banco**, roda-se
tudo, e o que quebrar quebra cedo.

```powershell
# 1. A TI provisiona o ADB-S e cria o usuário CENTRAL_IA (o bootstrap local
#    NÃO roda aqui: ele recusa APP_ENV diferente de dev, e ninguém tem SYS).
# 2. Baixe o wallet e extraia numa pasta.
# 3. Aponte o ambiente para lá:

$env:APP_ENV                    = "hml"
$env:ORACLE_DSN                 = "pociacentral_tp"
$env:ORACLE_WALLET_DIR          = "C:\wallets\pociacentral"
$env:ORACLE_WALLET_PASSWORD     = "<do Vault>"
$env:ORACLE_PASSWORD            = "<do Vault>"
$env:ORACLE_AUDITORIA_DIAS_IDLE = "31"

python -m migrations.oracle.runner --status   # o que falta
python -m migrations.oracle.runner            # aplica
```

O runner troca automaticamente o índice vetorial de IVF para HNSW quando
detecta wallet — é a única diferença de DDL entre os dois ambientes, e ela está
isolada num placeholder, não espalhada pelo SQL.

**Critério de aprovação do marco:** as duas migrações aplicam sem erro e
`/saude/pronto` responde `pronto` apontando para o ADB-S.

---

## 4. As variáveis que mudam por ambiente

Tudo o mais permanece igual ao `.env.example`.

| Variável | dev | hml / prd-poc |
|---|---|---|
| `APP_ENV` | `dev` | `hml` · `prd-poc` |
| `SECRET_PROVIDER` | `env` | `oci_vault` |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | `https://webhook.poc.bahrd.com.br` |
| `CORS_ORIGENS` | `["http://localhost:5173"]` | `["https://painel.poc.bahrd.com.br"]` |
| `ORACLE_DSN` | `oracle:1521/FREEPDB1` | nome do serviço do ADB-S |
| `ORACLE_WALLET_DIR` | vazio | caminho do wallet extraído |
| `ORACLE_AUDITORIA_DIAS_IDLE` | `0` | `31` |
| `MYSQL_HOST` | `mysql` | endpoint privado do HeatWave |
| `MYSQL_SSL_MODE` | `DISABLED` | `REQUIRED` |
| `REDIS_HOST` | `redis` | endpoint do OCI Cache |
| `REDIS_AUTH_TOKEN` | vazio | do Vault |
| `S3_ENDPOINT` | `http://minio:9000` | endpoint S3 da OCI |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel:4317` | endpoint do APM |
| `MODO_VOZ` | `voz_simulada` | `voz_livekit_sip` (só na VM de voz) |
| `VITE_API_BASE_URL` | `http://localhost:8000` | `https://api.poc.bahrd.com.br` |

`VITE_API_BASE_URL` é lida **em runtime** pelo entrypoint do nginx, não no
build. A mesma imagem `web` serve hml e prd-poc — validado: subindo a imagem
com `APP_ENV=hml` e outra URL, o `/config.js` sai correto.

---

## 5. Sequência do deploy

```
1. publicar          .\publicar.ps1 -Namespace <ns> -Versao <v>
2. migrar            job com a MESMA imagem: entrypoint das migrações
3. subir back-end    api + workers, com a etiqueta <v>
4. subir front-end   web, com a etiqueta <v>
5. verificar         GET /saude/pronto → "pronto"
```

**Ordem importa:** migrar antes de subir a aplicação. Como as migrações são
idempotentes e append-only, rodar o job duas vezes é inofensivo — subir código
que espera uma coluna que ainda não existe, não.

**Rollback:** voltar a etiqueta da imagem. Migração **não** volta — por isso
toda migração precisa ser compatível com a versão anterior do código (adicionar
coluna, nunca renomear numa única etapa).

---

## 6. O que falta, e de quem depende

| Item | Depende de | Sprint |
|---|---|---|
| `OciVaultSecretProvider` | O Vault existir e o Dynamic Group estar criado | 4 |
| Módulos Terraform | Conta da OCI e *compartment* | 3 e 4 |
| Escolha OKE × VMs Compute | Preferência do time de infra da Bahrd | 4 |
| Região (`sa-saopaulo-1` × `sa-vinhedo-1`) | Medição de latência (doc 02 §7.4) | 3 |
| VM do `voice-agent` | Respostas do suporte do GoTo (doc 02 §3.3) | 3 |
| **OCI Budgets com alerta** | Conta da OCI | **antes de tudo** |

O último não é burocracia: é o item que impede uma POC de virar uma fatura
inesperada. Vai antes de qualquer recurso ser ligado.
