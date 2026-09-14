# Auditoria do protótipo

O que estava faltando **antes** de eu começar a mexer, e como cada coisa foi
descoberta. Nenhum item abaixo é suposição: cada um tem o comando, o arquivo ou
o teste que o revelou.

> **Data da auditoria:** 11/09/2026 · **Commit auditado:** o estado herdado,
> antes do primeiro commit deste repositório.

---

## Método

Quatro passadas, nesta ordem. A ordem importa: a primeira é a única que não dá
para refazer depois que o repositório vira público.

| Passada | Ferramenta | O que procura |
|---|---|---|
| 1 · Segredo e dado pessoal | `gitleaks detect` · `git log -S` | Credencial e PII no **histórico**, não só na árvore |
| 2 · Identificadores de terceiro | `grep` por padrão numérico longo | Conta, dispositivo, registro — o que aponta para alguém |
| 3 · Prontidão de operação | leitura de `config.py`, `ci.yml`, `docker-compose.yml` | O que falta para o sistema ser operável por outra pessoa |
| 4 · Prontidão de deploy | leitura de `persistence/`, `Dockerfile` | O que quebra ao sair do notebook |

---

## O que já estava bom

Começar pelos defeitos dá uma impressão errada do ponto de partida. O que
estava certo, e economizou semanas:

| | Evidência |
|---|---|
| **953 testes**, sem tocar rede, banco nem API paga | `pytest -q` roda em 45 s num contêiner limpo |
| **CI com varredura de histórico** | `ci.yml` usa `fetch-depth: 0` — pega segredo removido depois |
| **Imagem multi-stage com alvo `runtime`** | `docker/backend.Dockerfile` |
| **Sondas separadas corretamente** | `/saude/vivo` não toca banco; `/saude/pronto` toca |
| **`oracledb` em modo *thin*** | sem `init_oracle_client` — Python puro, roda em ARM sem Instant Client |
| **Portas e adaptadores** | `domain/` não importa infraestrutura; trocar canal é variável de ambiente |

A última linha é o que mais vale. Foi ela que permitiu trocar o provedor de
WhatsApp sem tocar no agente, e é ela que vai permitir trocar de nuvem depois.

---

## Lacunas

Ordenadas por severidade, não por esforço.

### 🔴 Crítico — impediria publicar

**1 · Dado pessoal de cliente no histórico do Git.**
Um celular real e um endereço com número de porta, presentes **desde o commit
inicial**. Um commit posterior os removeu de um documento, e eles sobreviveram
em outro arquivo — porque a varredura de então olhou o documento, não a suíte.

```
git log --all -S"<o número>" --oneline     → 8 commits, do inicial ao de remoção
```

Por que é crítico: `git filter-repo` não resolve de verdade — deixa rastro em
*packfile* e não alcança clone já feito. A correção foi **histórico novo**, e
é o motivo de este repositório começar em um commit só.

**2 · Identificadores de conta de terceiro, fixos no código.**

| O quê | Onde |
|---|---|
| ID da conta WhatsApp Business | script de publicação de modelos, 2 linhas |
| 8 ids de modelo aprovado | manifesto de modelos |
| ids de conta e de número | um teste, copiados de um webhook real |
| 6 IMEIs de rastreador | ocorrências de amostra |

O IMEI é o mais silencioso dos quatro: o próprio `.gitignore` do projeto já o
classificava como dado que não se versiona, e ele estava versionado assim mesmo
— em código de amostra, que ninguém revisa com o mesmo cuidado que código de
produção.

### 🟠 Alto — quebra em produção

**3 · Ocorrências vivem na memória do processo.** ✅ **Resolvida em 14/09/2026.**
Reiniciar a API apagava as conversas em curso. Um *deploy* é um reinício, então
**toda entrega derrubava quem estava conversando**. Era a lacuna que mais pesava:
sem ela resolvida, automatizar o deploy pioraria o sistema em vez de melhorar.

As sessões passaram a ser espelhadas no Redis
([ADR-003](adr/0003-sessoes-fora-da-memoria.md)). Implementar revelou algo que a
auditoria não tinha visto: **a maior parte das mutações acontece no objeto
`Sessao`, e não nos métodos do depósito** — então não havia ponto único para
interceptar, e o plano original de gravar a cada mutação não funcionaria.

**4 · Assinatura HMAC do webhook desligada.**
A linha está comentada com a nota *"desligado para teste"*. Enquanto estiver
assim, quem descobrir a URL dispara um evento. O que segura hoje é uma lista
curta de números autorizados — que é controle de canal, não de origem.

**5 · A IA pode encerrar um pânico sozinha.**
`PANICO_AUTONOMO` está ligado, e o próprio `config.py` avisa: *"contraria o
princípio de que evento crítico é exclusivamente humano […] não vai para
produção assim"*. A lista branca de desfechos não protege aqui: ela garante que
o desfecho seja **válido**, não que seja o **certo**.

**6 · Não existe entrega contínua.**
O CI valida e para. Publicar é manual, e o script que publica é PowerShell —
não roda no runner Ubuntu. Sem CD não há deploy reproduzível, e sem deploy
reproduzível não há rollback.

**7 · Rollback não está definido nem foi testado.**
Há uma sequência de deploy esboçada, mas nenhum procedimento executado. E há um
detalhe que só aparece tentando: **migração não volta com a imagem**. Voltar a
etiqueta devolve o código, não o schema.

**8 · O pool do Oracle foi dimensionado para banco próprio.**
`ORACLE_POOL_MAX=10`, com `api` e `worker` em processos separados, pede até 20
sessões. O Autonomous Database no nível gratuito tem teto de **exatamente 20** —
sem folga para migração nem para o console. Estoura em produção, não no teste.

**9 · As imagens são x86; o destino é ARM.**
A instância gratuita da Oracle é Ampere. Imagem construída sem
`--platform linux/arm64` sobe e morre com `exec format error`. Descobrir isso
no dia da entrega custa uma noite.

### 🟡 Médio — falta de prática, não defeito

**10 · Sem versão, sem CHANGELOG, sem release.** Zero tags. `version = "0.1.0"`
parada no `pyproject.toml` desde o início, sem relação com o que está no ar.

**11 · Sem smoke test.** Nenhuma verificação automática de que o sistema
responde depois de publicado. Sem isso, o rollback não tem gatilho: alguém
precisa perceber que quebrou.

**12 · O painel usa segredo compartilhado, não autenticação.** Protege contra
quem descobre a URL; não responde "quem assumiu esta ocorrência?". Aceitável
com um operador, insuficiente com dois.

### 🟢 Baixo — conhecido e adiado com critério

**13 · Sem limite de taxa.** O teto de turnos limita o custo por conversa, mas
nada limita quantas conversas alguém abre.

**14 · Nome e placa vão para o modelo como estão.** Pseudonimizar antes de
montar o prompt é substituição de texto determinística — barata. Está adiada
porque hoje o dado é sintético.

---

## O que decidi **não** corrigir agora

Registrado para não parecer esquecimento.

| O quê | Por quê |
|---|---|
| Autenticação de operador | Resolve um problema que ainda não existe: há um operador |
| Limite de taxa | Mesmo motivo — um número, um remetente |
| Pseudonimização | Todo dado deste repositório já é sintético |
| Voz por telefone | Exige tronco e IP público; fora do escopo desta etapa |

A régua é a mesma nos quatro: **controle que protege um cenário inexistente é
código a manter sem risco a reduzir** — e trava de segurança mal calibrada
ensina o time a ignorá-la.

---

## O que muda por causa desta auditoria

Os itens 1 e 2 já estão corrigidos — foram a condição para este repositório
existir. Os demais viram fila, nesta ordem:

```
3 · sessões fora da memória      ✅ FEITO — ADR-003
8 · pool dimensionado para a nuvem ─┐
9 · imagem ARM                     ─┴─ bloqueiam o deploy funcionar
6 · entrega contínua
11 · smoke test                   ← vira o gatilho do rollback
7 · rollback definido E ensaiado
10 · versão, CHANGELOG, release
4 · religar o HMAC                ← antes do primeiro evento real
5 · decidir PANICO_AUTONOMO       ← decisão de operação, não de código
```

O item 3 vinha primeiro e não era negociável: automatizar entrega num sistema que
perde estado a cada reinício é automatizar a queda. Foi o primeiro a ser fechado,
e por isso.
