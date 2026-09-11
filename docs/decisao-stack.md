# Matriz de decisão de stack — critérios, pesos e escala

> ## ⚠️ Este documento está deliberadamente incompleto
>
> Ele traz **os critérios, os pesos e a escala de notas — e nada mais**. Nenhuma
> opção está listada, nenhuma nota foi dada.
>
> As notas entram em um commit **posterior**, e a separação é o ponto: pesar
> depois de olhar as opções faz a matriz virar espelho da preferência que já se
> tinha. O histórico do Git é o que torna essa ordem verificável — não a minha
> palavra.
>
> `git log --follow docs/decisao-stack.md` mostra os dois commits e as datas.

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

## O que vem a seguir

| Etapa | Onde |
|---|---|
| Levantar as opções e dar as notas | commit seguinte, **neste mesmo arquivo** |
| Registrar a decisão e o que se perde com ela | `docs/adr/0001-stack.md` |
| Decidir onde publicar | `docs/adr/0002-plataforma-de-publicacao.md` |

O ADR-001 não repete esta matriz: ele registra **a decisão e as consequências**,
inclusive as ruins. A matriz é a conta; o ADR é o que se assume por causa dela.
