# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [Não publicado]

### A fazer
- Sessões fora da memória do processo — hoje um reinício apaga as conversas em
  curso, e todo deploy é um reinício ([auditoria](docs/auditoria-prototipo.md),
  lacuna 3)
- Religar a assinatura HMAC do webhook (lacuna 4)
- Decidir `PANICO_AUTONOMO` — é decisão de operação, não de código (lacuna 5)

---

## [1.0.0] — 2026-09-21

Primeira versão publicada. O sistema deixa de existir só no notebook.

### Adicionado
- **Pilha de produção** (`docker-compose.prod.yml`): API, worker, Redis e borda
  em contêiner, com os dois bancos em serviço gerenciado na OCI
- **TLS automático** com Caddy e Let's Encrypt, com redirect de HTTP para HTTPS
- **Três smoke tests** (`tests/smoke/smoke.sh`): liveness com conferência de
  versão, readiness das três dependências, e painel com TLS e variáveis de
  ambiente conferidas
- **Entrega contínua** (`.github/workflows/cd.yml`): push na `main` constrói,
  publica em desenvolvimento, roda os smoke tests e só então toca produção
- **Ambientes separados** com GitHub Environments — segredos distintos, máquinas
  distintas, domínios distintos
- **Rollback automático** quando os smoke tests reprovam em produção, e
  `infra/deploy/rollback.sh` para o rollback manual, cronometrado
- **Runbook de deploy** ([`docs/08-runbook-deploy.md`](docs/08-runbook-deploy.md))
- **Post-mortem** do dado pessoal encontrado no histórico
  ([`docs/post-mortem-01-pii-no-historico.md`](docs/post-mortem-01-pii-no-historico.md))
- **C4 nível 1** ([contexto](docs/architecture/c4-nivel-1-contexto.md))
- **ADR-001** (manter a stack herdada) e **ADR-002** (publicar na Oracle Cloud),
  em formato MADR, com a matriz de decisão cujos pesos foram fixados antes das
  notas — a ordem é verificável no histórico do Git
- **Auditoria do protótipo** com 14 lacunas em quatro níveis de severidade

### Modificado
- `ORACLE_POOL_MAX` de 10 para **6**: `api` e `worker` em processos separados
  pediriam 20 sessões, e o teto do Autonomous Database gratuito é exatamente 20,
  sem folga para migração nem para o console
- Build fixado em `linux/amd64`, depois que a máquina ARM planejada não tinha
  capacidade na região
- `.gitattributes` trava LF em script, Dockerfile, Caddyfile e YAML — CRLF no
  shebang quebra só no servidor, nunca na máquina de quem escreveu

### Corrigido
- `.gitignore` não cobria `.env.prod`: o padrão do gitignore é literal, e `.env`
  sozinho não casa com `.env.prod`. O wallet do Autonomous Database e o
  `.deploy-anterior` também passaram a ser ignorados
- ADR-001 e ADR-002 descreviam uma infraestrutura que não foi a provisionada

### Segurança
- Histórico recriado do zero, sem o dado pessoal de cliente que existia desde o
  commit inicial
- `gitleaks` varrendo o **histórico** (`fetch-depth: 0`) no CI, e o mesmo
  `gitleaks` em hook de pre-commit
- Wallet do banco montado só-leitura a partir da máquina, nunca embutido na
  imagem publicada

[Não publicado]: https://github.com/Leonardolabdc/bahrd-ia/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Leonardolabdc/bahrd-ia/releases/tag/v1.0.0
