# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [Não publicado]

### A fazer
- Religar a assinatura HMAC do webhook (lacuna 4)
- Decidir `PANICO_AUTONOMO` — é decisão de operação, não de código (lacuna 5)

---

## [1.1.0] — 2026-09-15

O WhatsApp passa a funcionar de ponta a ponta pelo Twilio. Um evento entra, a
mensagem chega ao celular, a pessoa responde e a IA conduz a conversa.

### Adicionado
- **O canal Twilio consegue abrir conversa.** Ele respondia e nunca abria: a
  notificação chamava a Meta direto, sem olhar `CANAL_WHATSAPP`, e com as
  credenciais da Meta ausentes — o normal rodando em Twilio — desistia em
  silêncio. Template é conceito da Meta; o texto é reconstruído do manifesto e
  sai como mensagem comum, com os botões viram lista e o mapa vira link
- **Script de limpeza de conversas** ([`infra/deploy/limpar-sessoes.sh`](infra/deploy/limpar-sessoes.sh)),
  que recusa rodar em produção — apagar conversa viva é o que o ADR-003 impede
- **Nove testes novos** para o caminho do Twilio, que não tinha nenhum

### Corrigido
- **O Twilio exige o prefixo `whatsapp:` nos dois lados.** Recusava com
  `21910: Invalid From and To pair`. A normalização foi para dentro do cliente,
  não para o chamador: um lugar só que responde "como se endereça um número"
- **O nono dígito precisa sair do número de destino.** O Twilio respondia
  `201 Created` e, segundos depois, a mensagem virava `failed` com `63015` —
  falha assíncrona, invisível no momento do envio. O projeto já tinha a regra:
  o `_chave` canoniza tirando o nono, *"porque é a forma que a Meta usa"*. Ela
  existia para decidir **de quem** é uma mensagem que chega; faltava aplicá-la
  para decidir **para quem** vai uma que sai
- **Dezesseis testes cobriam o canal errado.** Passavam `object()` como
  configuração e nunca declaravam o canal, então exercitavam a Meta por
  acidente — num projeto cujo padrão é `twilio`. Agora cada um declara qual
  caminho percorre
- A evidência do rollback estava sendo ignorada pela regra global `*.log`

### Segurança
- Ao documentar o defeito do nono dígito, um celular real entrou num teste e
  numa docstring. O `test_nada_de_dado_real_no_repositorio`, criado por causa
  do [post-mortem 01](docs/post-mortem-01-pii-no-historico.md), pegou antes do
  commit. É a ação de causa raiz daquele incidente funcionando contra um erro
  que ninguém previu

---

## [1.0.0] — 2026-09-15

Primeira versão publicada. O sistema deixa de existir só no notebook.

### Adicionado
- **As conversas sobrevivem a um reinício.** Até aqui um deploy apagava toda
  conversa em andamento, e quem estava falando recebia o menu de ajuda no meio
  do atendimento. As sessões passam a ser espelhadas no Redis, e o boot recarrega
  o que estava vivo ([ADR-003](docs/adr/0003-sessoes-fora-da-memoria.md))
- **Os relógios de espera são rearmados** depois do reinício, descontando o tempo
  em que o processo esteve fora — quem pediu dez minutos espera dez, e não
  dezenove
- **ADR-003**, com a correção do que a implementação ensinou: gravar a cada
  mutação não era possível, porque quase toda mutação acontece no objeto
  `Sessao` e não nos métodos do depósito
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
- **Dois post-mortems**: o [dado pessoal no histórico do Git](docs/post-mortem-01-pii-no-historico.md)
  e [o primeiro deploy](docs/post-mortem-02-primeiro-deploy.md), que falhou dez
  vezes por dez causas diferentes — nenhuma visível em 970 testes verdes, porque
  todas viviam em ramos que só existem contra serviço gerenciado
- **C4 nível 1** ([contexto](docs/architecture/c4-nivel-1-contexto.md))
- **ADR-001** (manter a stack herdada) e **ADR-002** (publicar na Oracle Cloud),
  em formato MADR, com a matriz de decisão cujos pesos foram fixados antes das
  notas — a ordem é verificável no histórico do Git
- **Auditoria do protótipo** com 14 lacunas em quatro níveis de severidade
- **17 testes novos** — a suíte vai de 953 para **970**, sem regressão. Um deles
  não exercita comportamento: compara os campos do dataclass com o payload
  gravado e reprova quando alguém acrescenta um campo e esquece de serializá-lo

### Modificado
- `ORACLE_POOL_MAX` de 10 para **6**: `api` e `worker` em processos separados
  pediriam 20 sessões, e o teto do Autonomous Database gratuito é exatamente 20,
  sem folga para migração nem para o console
- Build fixado em `linux/amd64`, depois que a máquina ARM planejada não tinha
  capacidade na região
- `.gitattributes` trava LF em script, Dockerfile, Caddyfile e YAML — CRLF no
  shebang quebra só no servidor, nunca na máquina de quem escreveu

### Corrigido
- **Dez defeitos revelados pelo primeiro deploy**, cinco deles herdados do
  protótipo: senha do wallet ausente no runner de migração, retenção da
  auditoria acima do teto do Autonomous Database, TLS do MySQL montado como
  dicionário em vez de `SSLContext`, sonda do painel resolvendo para IPv6, e
  string vazia tratada como ausência na configuração do SPA. Todos detalhados
  no [post-mortem 02](docs/post-mortem-02-primeiro-deploy.md)
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

[Não publicado]: https://github.com/Leonardolabdc/bahrd-ia/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Leonardolabdc/bahrd-ia/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Leonardolabdc/bahrd-ia/releases/tag/v1.0.0
