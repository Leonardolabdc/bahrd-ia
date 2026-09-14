# ADR-001 · Manter a stack herdada do protótipo

- **Status:** aceita
- **Data:** 2026-09-12
- **Decide:** Leonardo Campos
- **Substitui:** —
- **Relacionada:** [ADR-002 · Plataforma de publicação](0002-plataforma-de-publicacao.md)

---

## Contexto e problema

O protótipo foi herdado funcionando: Python 3.12 com FastAPI no back-end, React
19 com Vite no painel, Oracle 26ai como sistema de registro, MySQL 8.4 como
camada operacional, Redis 7 como barramento, tudo em Docker. Passa 953 testes e
atende um evento de ponta a ponta.

**Funcionar no notebook não decide nada.** A pergunta é outra: esta é a stack
certa para publicar, operar e evoluir num prazo fixo de seis semanas, com uma
pessoa?

A dúvida é legítima porque a stack é grande para o volume desta etapa. Três
bancos distintos pedem três coisas para provisionar, três para monitorar e três
para explicar a quem chegar depois.

## Fatores de decisão

Os cinco critérios e seus pesos foram fixados em
[`decisao-stack.md`](../decisao-stack.md) **em 11/09/2026, antes de existir
qualquer opção para avaliar** — e as notas entraram em 12/09. A ordem é
verificável no histórico do Git, não na minha palavra.

| Critério | Peso |
|---|---:|
| Prazo até a URL pública | 30% |
| Risco de quebrar no caminho | 25% |
| Adequação ao problema | 20% |
| Custo de operação | 15% |
| Aderência ao mercado | 10% |

Quatro exigências do domínio compõem o critério de adequação, e uma delas
decide este ADR: **a trilha de auditoria precisa resistir a adulteração**,
porque uma ocorrência pode ser questionada meses depois.

## Opções consideradas

- **A · Manter** — FastAPI · React/Vite · Oracle · MySQL · Redis · Docker
- **B · Simplificar** — o mesmo, com **Postgres único** no lugar de Oracle + MySQL
- **C · Low-code** — n8n · Postgres · Slack
- **D · Serverless** — Vercel Functions · Supabase

C e D não entraram como figurantes: **C é a stack que a própria disciplina usa
nos protótipos dela**, e **D é o combo que o material recomenda para MVP**.

## Decisão

**Opção A — manter a stack herdada**, com duas mudanças de configuração
obrigatórias antes do deploy.

Total ponderado: **A 4,35 · B 2,95 · D 2,20 · C 1,85**.

C e D foram **eliminadas pela regra de corte** — nota 2 em adequação ao
problema elimina independentemente do total. A regra não foi decorativa: D somou
2,20, acima de C, e caiu do mesmo jeito.

### Por que A venceu, de verdade

A ponderação favorece o incumbente, e eu declarei isso no dia em que fixei os
pesos — antes de conhecer os números. Então refiz a conta **sem prazo e sem
risco**, só com os 45% de mérito:

| | A | B |
|---|:---:|:---:|
| Mérito puro | **4,78** | **4,11** |

A continua na frente, **por um motivo único: a auditoria imutável**. Tirando
esse critério, B ganharia — é mais simples, mais barata de operar e mais pedida
no mercado.

Manter não venceu por inércia. Venceu porque uma exigência do domínio existe em
uma opção só.

## Consequências

### Boas

- **Cinco dias até a URL pública**, contra quinze da alternativa mais próxima.
- **953 testes continuam valendo.** Nenhuma linha de teste é descartada.
- **A auditoria imutável vem do banco, não do código.** A `BLOCKCHAIN TABLE` do
  Oracle recusa alteração no nível do motor. Uma implementação em aplicação
  depende de quem escreve nela — e o ponto de uma trilha à prova de adulteração
  é justamente não depender disso.
- **Custo zero.** Os três bancos cabem na camada gratuita permanente da Oracle.
- **Os adaptadores continuam sendo adaptadores.** `domain/` não conhece
  infraestrutura, então esta decisão é reversível a um custo conhecido.

### Ruins — e são reais

- **Três bancos para uma pessoa operar.** Três coisas para provisionar,
  monitorar, migrar e explicar. Para o volume desta etapa, é excesso — e o
  excesso não some por estar justificado.
- **A stack é maior que o problema de hoje.** Ela foi desenhada para 43 mil
  eventos por mês. Nesta etapa o volume é de demonstração.
- **Oracle quase não aparece em vaga de engenheiro de IA.** É o único critério
  em que A perde para B, e o repositório também é portfólio.
- **Amarra a nuvem.** O Autonomous Database só existe na Oracle Cloud. Trocar de
  provedor deixou de ser barato, e isso alimenta diretamente o ADR-002.
- **O teto de 20 sessões simultâneas** do banco gratuito obriga a reduzir o pool
  de conexões. É configuração, mas é uma restrição que não existia antes.
- **A imagem precisa declarar a plataforma.** Build sem `--platform` explícito
  pega a arquitetura de quem constrói, e num Mac com chip M isso gera uma
  imagem que sobe na nuvem e morre com `exec format error`.

### Mudanças obrigatórias que esta decisão implica

| O quê | De | Para | Por quê |
|---|---|---|---|
| `ORACLE_POOL_MAX` | 10 | **6** | `api` + `worker` pediriam 20 sessões; o teto do banco gratuito é exatamente 20, sem folga para migração |
| Build da imagem | implícito | **`linux/amd64`** | As máquinas gratuitas provisionadas são x86 ([ADR-002](0002-plataforma-de-publicacao.md)) |

> **Nota de 14/09/2026.** Este ADR previa build ARM, porque o plano era usar a
> máquina Ampere. A capacidade dessa máquina não existia na região, e o deploy
> acabou em máquinas x86 — o que **elimina** a exigência de arquitetura em vez
> de complicá-la. O registro completo está na
> [atualização do ADR-002](0002-plataforma-de-publicacao.md#atualização--14092026--a-máquina-mudou-a-decisão-não).

## Gatilho de revisão

Esta decisão tem uma dependência única e declarada. **Se a exigência de trilha
de auditoria à prova de adulteração deixar de valer** — por mudança de escopo,
de contrato ou de entendimento jurídico — então a Opção B passa à frente no
mérito, e este ADR deve ser revisto.

Não é ressalva de rodapé: é a condição em que a decisão inverte.

## Mais informação

- A matriz completa, com as notas e o porquê de cada uma:
  [`decisao-stack.md`](../decisao-stack.md)
- O estado do protótipo antes desta decisão:
  [`auditoria-prototipo.md`](../auditoria-prototipo.md)
- Onde este sistema será publicado:
  [ADR-002](0002-plataforma-de-publicacao.md)
