# Runbook · do zero ao ar

O que rodar, em que ordem, para pôr o Bahrd no ar nas duas máquinas da OCI e
ligar a entrega contínua. Cada bloco é copiável. Onde houver `SEU-...`, troque.

> **Antes de começar**, tenha em mãos: o token do DuckDNS, o wallet do
> Autonomous Database (.zip), o endereço privado e a senha do MySQL HeatWave, e
> a chave SSH em `~/.ssh/bahrd.key`.

| Papel | Máquina | IP | Domínio |
|---|---|---|---|
| **Produção** | `bahrd-app` | 64.181.191.98 | `SEU-DOMINIO.duckdns.org` |
| **Desenvolvimento** | `bahrd-worker` | 168.138.147.121 | `SEU-DOMINIO-dev.duckdns.org` |

> A máquina chamada `bahrd-worker` passa a ser o ambiente de desenvolvimento —
> o nome ficou do plano antigo, em que havia uma máquina só e o worker morava
> separado. Renomear o *display name* no console da OCI é gratuito e leva 30
> segundos; não muda nada tecnicamente, mas evita confusão no vídeo.

---

## 1 · DNS

Em [duckdns.org](https://www.duckdns.org), entre com o GitHub e crie **dois**
subdomínios. Aponte cada um para o IP correspondente da tabela acima.

Confira antes de seguir — o Let's Encrypt só emite certificado se o DNS já
resolver:

```bash
nslookup SEU-DOMINIO.duckdns.org
nslookup SEU-DOMINIO-dev.duckdns.org
```

## 2 · Preparar cada máquina

As duas máquinas são **Ubuntu 24.04**, usuário `ubuntu`. Docker 29.8 e Compose
v5.5.1 já vêm instalados e o usuário já está no grupo `docker` — nada disso
precisa ser feito.

```bash
ssh -i ~/.ssh/bahrd.key ubuntu@64.181.191.98
```

Já dentro da máquina:

```bash
sudo apt-get update -qq && sudo apt-get install -y -qq git
sudo mkdir -p /opt/bahrd && sudo chown "$USER":"$USER" /opt/bahrd
git clone https://github.com/Leonardolabdc/bahrd-ia.git /opt/bahrd
cd /opt/bahrd
```

**Portas 80 e 443.** A `bahrd-app` já está com elas abertas; a de
desenvolvimento não. O comando abaixo é idempotente — não duplica a regra se ela
já existir:

```bash
for porta in 80 443; do
  sudo iptables -C INPUT -p tcp --dport $porta -m state --state NEW -j ACCEPT 2>/dev/null     || sudo iptables -I INPUT "$(sudo iptables -L INPUT --line-numbers -n | awk '/REJECT/{print $1; exit}')"          -p tcp --dport $porta -m state --state NEW -j ACCEPT
done
sudo netfilter-persistent save
sudo iptables -L INPUT -n --line-numbers | head -12
```

> ⚠️ **A regra precisa entrar ANTES da linha `REJECT`**, e é por isso que o
> comando descobre a posição dela em vez de usar um número fixo. `iptables -A`,
> que acrescenta no fim, colocaria a regra depois do REJECT — onde ela não tem
> efeito nenhum, e sem nenhum erro para avisar. Já aconteceu neste projeto.

> As *Ingress Rules* da sub-rede pública, no console da OCI, precisam liberar
> 80 e 443 também. São duas camadas de firewall, e esquecer a de cima dá o
> mesmo sintoma de esquecer a de baixo: silêncio.

## 3 · Wallet e configuração

Do seu Windows, envie o wallet para **cada** máquina:

```bash
# Descompacte o .zip do console da OCI numa pasta local primeiro
scp -i ~/.ssh/bahrd.key -r ./wallet ubuntu@64.181.191.98:/opt/bahrd/wallet
```

Na máquina, crie o arquivo de ambiente:

```bash
cd /opt/bahrd
cp .env.prod.example .env.prod
chmod 600 .env.prod          # só o dono lê — é onde moram os segredos
nano .env.prod
```

Preencha, no mínimo:

| Variável | Produção | Desenvolvimento |
|---|---|---|
| `APP_ENV` | `prd-poc` | `dev` |
| `DOMINIO` | seu domínio | seu domínio de dev |
| `EMAIL_ACME` | seu e-mail | o mesmo |
| `PUBLIC_BASE_URL` | `https://` + domínio | idem, o de dev |
| `CORS_ORIGENS` | `["https://SEU-DOMINIO.duckdns.org"]` | idem |
| `GHCR_OWNER` | `leonardolabdc` | idem |
| `ORACLE_*` | usuário, senha, DSN e senha do wallet | **outros valores** |
| `MYSQL_HOST` / `MYSQL_PASSWORD` | o endereço privado e a senha | **outros valores** |
| `PAINEL_TOKEN` | um valor longo e aleatório | **outro valor** |

> **Os segredos das duas máquinas precisam ser diferentes.** É isso que a
> rubrica chama de "ambientes realmente separados". Dois arquivos com a mesma
> senha são um ambiente só, servido em dois endereços.
>
> Para gerar: `openssl rand -hex 32`

## 3.5 · Tornar as imagens públicas

**Este passo não é opcional, e é o que mais trava sem dar pista.**

Pacotes no GitHub Container Registry nascem **privados**, mesmo quando o
repositório é público. A máquina tenta baixar a imagem, recebe `denied` ou
`unauthorized`, e a mensagem não diz que o problema é visibilidade.

Depois que o CD rodar pela primeira vez e publicar as imagens:

1. GitHub → sua foto → **Your packages**
2. Abra `bahrd-backend` → **Package settings** → *Danger Zone* →
   **Change visibility** → *Public*
3. Repita para `bahrd-web`

Com isso a máquina baixa sem credencial nenhuma, e o `docker login` deixa de ser
necessário no servidor. A alternativa seria guardar um token de leitura em cada
máquina — mais uma credencial para rotacionar, em troca de nada: a imagem é
construída a partir de um repositório que já é público.

## 4 · Primeiro deploy, à mão

Antes de automatizar, prove que funciona uma vez. Em cada máquina:

```bash
cd /opt/bahrd
./infra/deploy/deploy.sh sha-$(git rev-parse --short HEAD)
```

Da sua máquina, confira de fora:

```bash
bash tests/smoke/smoke.sh https://SEU-DOMINIO.duckdns.org
```

Os três precisam passar. Se o terceiro falhar por TLS, dê ao Caddy um ou dois
minutos: a primeira emissão do certificado não é instantânea.

## 5 · Ligar a entrega contínua

No GitHub, em **Settings → Environments**, crie `dev` e `prod`. Em **cada um**,
cadastre:

| Tipo | Nome | Valor |
|---|---|---|
| Secret | `SSH_HOST` | o IP daquela máquina |
| Secret | `SSH_USER` | `ubuntu` |
| Secret | `SSH_KEY` | o conteúdo de `~/.ssh/bahrd.key`, inteiro |

> Para copiar a chave sem errar a seleção: `cat ~/.ssh/bahrd.key | clip`.
> Faltar uma linha é a causa mais comum de falha aqui, e o SSH não diz que o
> problema é a chave.
>
> ⚠️ **`BASE_URL` é _variable_, não _secret_.** O workflow lê `vars.BASE_URL`,
> que não enxerga secrets — como secret, ele leria vazio e o smoke test rodaria
> contra uma URL em branco. E o GitHub **mascara secrets nos logs**: o endereço
> apareceria como `***` justamente na saída que se mostra numa demonstração.
| Variable | `BASE_URL` | `https://` + o domínio daquela máquina |

> A chave privada vai no **secret do GitHub**, nunca no repositório. E não
> reaproveite: gere um par por ambiente se quiser ser rigoroso.

**Por último, ligue o deploy.** Em **Settings → Secrets and variables → Actions
→ Variables**, na aba do **repositório** (não do Environment), crie:

| Nome | Valor |
|---|---|
| `DEPLOY_HABILITADO` | `true` |

Enquanto ela não existir, os dois jobs de deploy ficam **pulados** — o pipeline
continua verde e nada é publicado. É proposital: pipeline vermelho por
configuração ausente treina todo mundo a ignorar pipeline vermelho.

> Tem que ser variável de **repositório**. O `if` de um job é avaliado antes de
> o ambiente ser resolvido, então uma variável de Environment leria vazia
> sempre, e o deploy ficaria eternamente pulado sem ninguém entender por quê.

Depois disso, um push na `main` publica sozinho: constrói, sobe em dev, roda os
smoke tests, e só então toca produção.

## 6 · Ensaiar o rollback

**Antes de precisar.** O ADR-002 registra que uma máquina virtual não tem
rollback de plataforma, e um procedimento nunca executado não é procedimento.

```bash
ssh -i ~/.ssh/bahrd.key ubuntu@64.181.191.98
cd /opt/bahrd
cat .deploy-anterior            # a etiqueta que o deploy guardou
./infra/deploy/rollback.sh      # volta, e roda os smoke tests sozinho
```

O script cronometra e imprime o tempo. **Anote esse número** — é a evidência que
a entrega pede, e é a resposta para "quanto tempo você leva para voltar?".

---

## Quando algo der errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Certificado não emite | DNS ainda não propagou, ou porta 80 fechada | `nslookup`; conferir as duas camadas de firewall |
| `/saude/pronto` devolve 503 no `oracle` | Wallet ausente, senha errada, ou `ORACLE_DSN` não bate | `docker compose -f docker-compose.prod.yml logs api` |
| `/saude/pronto` devolve 503 no `mysql` | A máquina não alcança a sub-rede privada | Conferir a rota e a *security list* da sub-rede do HeatWave |
| API morre sozinha | 1 GB acabou | `free -h`; conferir se o swap está ativo |
| `denied` ou `unauthorized` no pull | Pacote do GHCR ainda privado | Passo 3.5 — tornar `bahrd-backend` e `bahrd-web` públicos |
| `bad interpreter` num script | Fim de linha CRLF | O `.gitattributes` previne; confirmar que o clone é recente |
| Deploy passa mas a versão não muda | Etiqueta não mudou, ou pull não trouxe | O smoke test 1 pega exatamente isso |

## Relacionados

- Onde publicar, e por quê: [ADR-002](adr/0002-plataforma-de-publicacao.md)
- As lacunas que o deploy fecha: [auditoria](auditoria-prototipo.md)
- Custo por serviço: [`06-custo-mensal.md`](06-custo-mensal.md)
