# Matriz de decisão de stack — critérios, pesos e escala

> ## ℹ️ Os pesos foram fixados antes de existir opção para avaliar
>
> Este documento nasceu em **11/09/2026** com os critérios, os pesos e a escala
> — e **nenhuma opção listada, nenhuma nota dada**. As opções e as notas entraram
> em **12/09/2026**, no commit seguinte.
>
> A separação é o ponto. Pesar depois de olhar as opções faz a matriz virar
> espelho da preferência que já se tinha. O histórico do Git é o que torna essa
> ordem verificável — não a minha palavra:
>
> ```
> git log --follow --format="%ad  %s" --date=short docs/decisao-stack.md
> ```

---

## A decisão que esta matriz resolve

**Manter a stack herdada do protótipo, ou trocar?**

O protótipo chegou com Python/FastAPI no back-end, React/Vite no painel, Oracle
como sistema de registro, MySQL como camada operacional, Redis como barramento
e Docker para tudo. Ele **funciona** — 953 testes passando, atendimento de ponta
a ponta.

Isso não decide nada sozinho. Funcionar no notebook e ser a escolha certa para
publicar, operar e evoluir são perguntas diferentes, e a segunda é a que esta
matriz responde.

**Não está em jogo aqui:** onde publicar. Essa é uma decisão à parte, e vai para
o ADR-002 com a sua própria matriz.

---

## O que esta matriz otimiza

Antes dos critérios, a premissa que os ordena — porque um critério só tem peso
em relação a um objetivo.

> **A entrega tem data: semana 6.** O projeto precisa estar publicado, com
> pipeline, versão e rollback ensaiado, num prazo fixo e sem equipe. Diante
> disso, **prazo e risco pesam mais que elegância ou aderência a modismo.**

Isso tem uma consequência que eu prefiro declarar agora, antes de saber as
notas: **esta ponderação favorece manter o que existe.** Quem já tem algo
funcionando ganha em "prazo" e em "risco" por definição.

Duas travas contra isso virar profecia autorrealizável:

1. **"Adequação ao problema" tem peso 20%** e é indiferente a quem chegou
   primeiro — mede se a tecnologia serve ao que o sistema faz, não se já está
   escrita.
2. **A conclusão precisa declarar o que se perde.** Uma matriz que recomenda
   manter e não lista nenhuma consequência ruim não foi honesta; foi decorativa.

---

## Os cinco critérios

Cada um traz **como será medido**. Critério sem definição operacional recebe a
nota que o autor quiser — e aí a matriz não decide nada, só registra.

### 1 · Prazo até a URL pública — peso **30%**

*Quanto tempo, em dias de trabalho, da decisão até um endereço público
respondendo.*

Como medir: soma de (a) código a escrever ou reescrever, (b) infraestrutura a
provisionar, (c) o que precisa ser aprendido antes de começar.

Por que é o maior: é o único critério com prazo externo. Os outros quatro
admitem "resolvemos depois"; este, não.

### 2 · Risco de quebrar no caminho — peso **25%**

*Qual a chance de aparecer um bloqueio que não dá para contornar no prazo.*

Como medir: quantidade de partes ainda não exercitadas de ponta a ponta, e
existência de plano B para cada uma.

Por que é o segundo: num prazo fixo, o risco não se paga com esforço extra —
ele se paga com escopo cortado. Risco alto não atrasa a entrega, **reduz** a
entrega.

### 3 · Adequação ao problema — peso **20%**

*A tecnologia serve ao que este sistema precisa fazer?*

Como medir, pelas quatro exigências concretas do domínio:

| Exigência | Vem de |
|---|---|
| Conversa assíncrona, com espera e retomada | o cliente responde em minutos ou em horas |
| Áudio nos dois sentidos | motorista dirigindo manda nota de voz |
| Trilha de auditoria à prova de adulteração | ocorrência pode ser questionada depois |
| Decisão determinística **antes** do modelo | evento crítico não pode depender de IA |

Este é o critério que **não** favorece o incumbente: ele mede a tecnologia
contra o problema, não contra o calendário.

### 4 · Custo de operação — peso **15%**

*Quanto custa por mês manter no ar, no volume desta etapa.*

Como medir: soma mensal de infraestrutura, banco, modelo e canal de mensagem,
com a camada gratuita de cada fornecedor já descontada.

Por que só 15%: no volume desta etapa, a diferença entre as alternativas é de
dezenas de reais. Dar peso maior a um critério cuja variação é pequena distorce
o resultado sem melhorar a decisão.

### 5 · Aderência ao mercado — peso **10%**

*O quanto esta stack aparece no que se pede de um engenheiro de IA.*

Como medir: presença em anúncio de vaga e tamanho do ecossistema — biblioteca
mantida, documentação, resposta a problema comum.

Por que é o menor, e por que continua na lista: é real — o repositório também é
portfólio. Mas é o único critério que não afeta o sistema funcionar, e por isso
não pode decidir nada sozinho.

---

## A tabela de pesos

| # | Critério | Peso | Natureza |
|---|---|---:|---|
| 1 | Prazo até a URL pública | **30%** | restrição externa |
| 2 | Risco de quebrar no caminho | **25%** | restrição externa |
| 3 | Adequação ao problema | **20%** | mérito técnico |
| 4 | Custo de operação | **15%** | mérito econômico |
| 5 | Aderência ao mercado | **10%** | valor de carreira |
| | **Total** | **100%** | |

**55% em restrição externa, 45% em mérito.** É o retrato honesto de um trabalho
com data marcada — e a leitura correta é que, sem o prazo, os pesos seriam
outros. Uma matriz é sempre a fotografia de um contexto, não uma verdade.

---

## A escala de notas

Fixada aqui, antes de existir opção para avaliar. Sem isso, "nota 4" significa
o que for conveniente no momento de escrever.

| Nota | Significado |
|---:|---|
| **5** | Atende plenamente, sem ressalva |
| **4** | Atende, com uma limitação conhecida e contornável |
| **3** | Atende parcialmente; exige trabalho adicional previsível |
| **2** | Atende mal; o contorno é caro ou frágil |
| **1** | Não atende |

**Cálculo:** nota × peso, somado. Máximo possível 5,00.

**Regra de corte, também definida antes:** opção com nota **1 ou 2** em
*Adequação ao problema* está **eliminada**, independentemente do total. Um
sistema que não serve ao problema não melhora por ser rápido de entregar.

---

## As opções avaliadas

Quatro caminhos que um engenheiro razoável consideraria para este problema. Não
são quatro variações do mesmo: são quatro apostas diferentes sobre o que importa.

| | Opção | A aposta |
|---|---|---|
| **A** | **Manter** — FastAPI · React/Vite · Oracle · MySQL · Redis · Docker | O que já passa em 953 testes é o ativo mais valioso |
| **B** | **Simplificar** — FastAPI · React/Vite · **Postgres único** · Redis | Três bancos para um sistema deste tamanho é peso morto |
| **C** | **Low-code** — n8n · Postgres · Slack | Isto é roteamento de mensagem, não engenharia de software |
| **D** | **Serverless** — Vercel Functions · Supabase | Pagar por execução e não por tempo ligado |

As opções C e D não são palha: **C é a stack que a própria disciplina usa nos
protótipos dela**, e **D é o combo que o material da Aula 3 recomenda para MVP**.
Se a matriz as elimina, precisa dizer por quê — e diz, abaixo.

---

## As notas

### Critério 1 · Prazo até a URL pública — peso 30%

| | Nota | Por quê |
|---|:---:|---|
| **A** | **4** | Código pronto e passando. Falta configuração (pool do banco, imagem ARM) e provisionar três serviços. **~5 dias.** A limitação que impede o 5: três bancos para provisionar em vez de um |
| **B** | **2** | Reescrever a camada de persistência do Oracle, converter 6 migrações SQL, refazer os testes que tocam nelas. **~15 dias**, e é trabalho sem funcionalidade nova no fim |
| **C** | **1** | Playbooks, blindagem de saída, motor de políticas e 953 testes não aproveitam nada. É recomeçar. **~30 dias** |
| **D** | **1** | Função com tempo limitado não segura conversa que espera horas. O worker de espera e retomada teria de ser reescrito sobre outro mecanismo. **~20 dias** |

### Critério 2 · Risco de quebrar no caminho — peso 25%

| | Nota | Por quê |
|---|:---:|---|
| **A** | **4** | Três partes ainda não exercitadas: o banco gerenciado de verdade, o MySQL gerenciado e a arquitetura ARM. **As três têm plano B** — o contêiner local continua rodando. Nenhuma é caminho sem volta |
| **B** | **2** | O risco concentra onde não há plano B: a trilha de auditoria imutável **não tem equivalente** fora do Oracle. Reimplementar encadeamento por hash é escrever de novo o que já existe pronto |
| **C** | **1** | Nada exercitado, e o pior: o motor de políticas vira nó visual e **deixa de ter teste unitário**. A parte que não pode falhar perde a rede que hoje a protege |
| **D** | **2** | Partida a frio contra um webhook que precisa responder rápido, e função com tempo limitado contra conversa longa. Os dois aparecem em produção, não no teste |

### Critério 3 · Adequação ao problema — peso 20%

Medido contra as quatro exigências fixadas ontem.

| | Assíncrono | Áudio | Auditoria imutável | Decisão antes do modelo | Nota |
|---|:---:|:---:|:---:|:---:|:---:|
| **A** | ✅ | ✅ | ✅ | ✅ | **5** |
| **B** | ✅ | ✅ | ❌ | ✅ | **3** |
| **C** | ⚠️ | ⚠️ | ❌ | ⚠️ | **2** |
| **D** | ❌ | ✅ | ❌ | ✅ | **2** |

O que cada falha significa:

- **B perde a auditoria imutável.** O Postgres não tem tabela que recusa
  alteração. Dá para simular com encadeamento por hash na aplicação — mas aí a
  garantia depende do código, e o ponto de uma trilha à prova de adulteração é
  justamente **não** depender de quem escreve nela.
- **C enfraquece as quatro.** Espera e retomada existem no n8n, e áudio também,
  mas o determinismo vira desenho visual: o motor de políticas deixa de ser
  código testável e vira configuração que só se valida executando.
- **D falha no assíncrono, que é o coração.** Uma conversa por WhatsApp fica
  aberta por horas. Função serverless não fica.

### Critério 4 · Custo de operação — peso 15%

| | Nota | Por quê |
|---|:---:|---|
| **A** | **5** | **R$ 0/mês.** Banco de registro, banco operacional e máquina cabem na camada gratuita permanente da Oracle |
| **B** | **5** | **R$ 0/mês** também — Postgres gerenciado tem camada gratuita |
| **C** | **4** | ~US$ 5/mês para manter o n8n de pé 24 h |
| **D** | **4** | R$ 0, com uma ressalva: o banco gerenciado **pausa após 7 dias sem atividade**, e projeto acadêmico fica ocioso |

### Critério 5 · Aderência ao mercado — peso 10%

| | Nota | Por quê |
|---|:---:|---|
| **A** | **4** | FastAPI e React são altíssima demanda. Oracle aparece pouco em vaga de engenheiro de IA — é onde perde o ponto |
| **B** | **5** | FastAPI + Postgres é o par mais pedido que existe nessa função |
| **C** | **3** | n8n cresce em anúncio, mas ainda é nicho, e não demonstra engenharia de software |
| **D** | **4** | Combo muito pedido em produto novo |

---

## O resultado

| Critério | Peso | **A** manter | **B** simplificar | **C** low-code | **D** serverless |
|---|---:|:---:|:---:|:---:|:---:|
| Prazo até a URL pública | 30% | 4 | 2 | 1 | 1 |
| Risco de quebrar no caminho | 25% | 4 | 2 | 1 | 2 |
| Adequação ao problema | 20% | 5 | 3 | 2 | 2 |
| Custo de operação | 15% | 5 | 5 | 4 | 4 |
| Aderência ao mercado | 10% | 4 | 5 | 3 | 4 |
| **Total ponderado** | | **4,35** | **2,95** | **1,85** | **2,20** |
| **Regra de corte** | | — | — | ⛔ eliminada | ⛔ eliminada |

**A regra de corte funcionou, e vale registrar que ela não foi decorativa.** C e
D tiraram 2 em *Adequação ao problema* e estão eliminadas independentemente do
total — o que só importa porque **D tirou 2,20, acima de C, e ainda assim caiu**.
Uma regra que nunca elimina ninguém é enfeite.

### O teste que eu devo a quem lê

A ponderação favorece o incumbente — eu disse isso ontem, antes de saber os
números. Então a pergunta honesta é: **e se o prazo não existisse?**

Refazendo a conta só com os 45% de mérito (adequação, custo, mercado),
normalizados:

| | A | B |
|---|:---:|:---:|
| Mérito puro, sem prazo nem risco | **4,78** | **4,11** |

**A continua na frente, e por um motivo só: a auditoria imutável.** Tirando esse
critério, B ganharia — é mais simples, mais barato de operar e mais pedido no
mercado.

Isso muda a leitura da decisão. Manter não venceu por inércia: venceu porque
*uma* exigência do domínio só existe em uma das opções. Se essa exigência cair,
a decisão deve ser revista — e é isso que vai para o ADR-001 como gatilho de
revisão, não como nota de rodapé.

---

## O que vem a seguir

| Etapa | Onde |
|---|---|
| Registrar a decisão e o que se perde com ela | `docs/adr/0001-stack.md` |
| Decidir onde publicar | `docs/adr/0002-plataforma-de-publicacao.md` |

O ADR-001 não repete esta matriz: ele registra **a decisão e as consequências**,
inclusive as ruins. A matriz é a conta; o ADR é o que se assume por causa dela.
