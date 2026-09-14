# ADR-003 · Tirar as conversas da memória do processo

- **Status:** aceita
- **Data:** 2026-09-14
- **Decide:** Leonardo Campos
- **Depende de:** [ADR-002 · Plataforma de publicação](0002-plataforma-de-publicacao.md)

---

## Contexto e problema

As conversas em curso vivem num dicionário dentro do processo da API. Reiniciar
o processo apaga todas.

Isso era tolerável enquanto o sistema rodava num notebook, onde reiniciar é uma
decisão consciente de quem está olhando a tela. Deixa de ser no momento em que
existe entrega contínua, porque **todo deploy é um reinício**.

O efeito é pior do que perder dado. Quem está conversando não recebe erro: a
próxima mensagem do motorista chega a um sistema que não sabe quem ele é, e é
tratada como conversa nova. Ele responde "sim" a uma pergunta que, do lado de
cá, nunca foi feita.

**Automatizar a entrega sem resolver isto é automatizar a queda.** Está
registrado como lacuna 3 da [auditoria](../auditoria-prototipo.md), e é o único
item que a auditoria marcou como bloqueante.

## Fatores de decisão

Os mesmos pesos da [matriz](../decisao-stack.md), fixados em 11/09 antes de
existir opção. Dois deles decidem aqui:

| Critério | Peso | Por que pesa nesta decisão |
|---|---:|---|
| **Prazo até a URL pública** | 30% | A entrega é em 21/09. O que não couber não existe |
| **Risco de quebrar no caminho** | 25% | Mexer no estado de 12 métodos síncronos é onde mora o risco |
| Adequação ao problema | 20% | A sessão é estado quente e efêmero, com validade própria |
| Custo de operação | 15% | Nenhuma opção aqui custa dinheiro; custam trabalho |
| Aderência ao mercado | 10% | Praticamente empatado entre as opções |

Uma restrição do domínio filtra antes de qualquer nota: **sessão tem prazo de
validade**. Conversa parada vira conversa morta, por regra que já existe no
código. Persistir sessão não é arquivar — é sobreviver a um reinício.

## Opções consideradas

- **A · Espelho *write-through* no Redis** — toda mutação grava a sessão; o boot
  recarrega o que estava vivo
- **B · Reescrever para gravação assíncrona** — as mutações viram eventos numa
  fila, e um consumidor materializa o estado
- **C · Persistir no MySQL** — a sessão vira tabela, junto da ocorrência
- **D · Drenar antes de cada deploy** — parar de aceitar evento novo, esperar as
  conversas fecharem, então publicar

## Decisão

**Opção A — espelho *write-through* no Redis.**

O Redis já está na pilha, já é o barramento, já tem AOF ligado e já sobrevive ao
restart do contêiner. A sessão passa a ser gravada fora do processo e relida no
boot. Nenhum componente novo entra na arquitetura.

> **Correção de 14/09, escrita durante a implementação.** Este ADR dizia
> *"gravada a cada mutação"*. Implementar mostrou que isso não é possível sem
> reescrever o módulo, e a razão está nos chamadores: **a maior parte das
> mutações acontece no objeto `Sessao`** — `sessao.registrar_ia(...)`,
> `sessao.encerrar(...)` — e não nos métodos de `Sessoes`. Não existe ponto
> único para interceptar, e interceptar os doze métodos do depósito pegaria uma
> fração das mudanças. A fração que escapasse seria invisível: a sessão voltaria
> do reinício com o valor antigo, sem erro em lugar nenhum.
>
> **O que foi construído:** grava, na saída de cada requisição, toda sessão viva
> cujo payload mudou. A comparação é do objeto inteiro, então não existe mutação
> que escape — não importa quem mudou o quê, nem onde.
>
> **O que isso custa:** a janela de perda deixa de ser zero e passa a ser uma
> requisição. Num desligamento gracioso — que é o caso do deploy, e o motivo
> deste ADR — ela continua sendo zero, porque o gancho de saída grava antes de
> morrer. O que se perde é o cenário de morte abrupta, tipo `OOM killer`, em que
> se perde o último turno de cada conversa em andamento. Com 1 GB de memória
> ([ADR-002](0002-plataforma-de-publicacao.md)) esse cenário não é hipotético, e
> aceitá-lo é uma escolha, não um descuido.

### Por que as outras caem

| | Por quê |
|---|---|
| **B · Gravação assíncrona** | É a resposta certa para volume alto, e errada para este prazo. Troca um problema resolvido hoje por uma janela em que o estado materializado está atrás do real — e é justamente nessa janela que o deploy acontece. Pesa contra em prazo (30%) e em risco (25%), que somam 55% |
| **C · MySQL** | Tecnicamente funciona, e o banco já existe. Mas exige *schema*, migração e mapeamento de 36 campos, três deles dataclasses aninhadas — trabalho de dias, para guardar dado que expira em horas. E acrescenta ida ao banco no caminho de cada turno da conversa |
| **D · Drenar antes do deploy** | Não é solução, é a ausência dela com outro nome. Torna o deploy dependente de o cliente responder, o que é exatamente o que ninguém controla. E um pânico aberto poderia adiar uma correção de segurança indefinidamente |

### O que decide, de verdade

A opção A vence **porque a sessão é estado quente e efêmero, e o Redis é o único
componente da pilha que já foi escolhido para exatamente isso**. As outras três
tratam a sessão como se fosse registro permanente — e ela não é. O registro
permanente já existe: é a `BLOCKCHAIN TABLE` do Oracle, decidida no
[ADR-001](0001-stack.md), e ela não está em questão aqui.

## Consequências

### Boas

- **O deploy deixa de derrubar conversa.** É o objetivo, e é o que destrava a
  entrega contínua do [ADR-002](0002-plataforma-de-publicacao.md).
- **Nenhum componente novo.** Menos uma coisa para provisionar, monitorar e
  explicar — o oposto do que o ADR-001 já reconheceu como excesso.
- **A mudança é local.** A classe `Sessoes` ganha um colaborador; os 12 métodos
  continuam síncronos e a assinatura pública não muda. Quem chama não sabe.
- **O AOF já estava ligado**, e por este motivo. A decisão anterior de ligá-lo
  paga aqui.

### Ruins — e uma exige decisão de operação

- **O Redis vira dependência de correção, não só de desempenho.** Antes, Redis
  fora do ar degradava a fila. Agora, perde sessão. É a troca que esta decisão
  faz, e ela é consciente.
- **Gravar a cada mutação é gravar muito.** Cada turno de conversa escreve a
  sessão inteira, e não o delta. Para o volume desta etapa é irrelevante; para
  43 mil eventos/mês, vira a opção B.
- **Os relógios de espera não sobrevivem.** `_ESPERAS` guarda `asyncio.Task`, e
  tarefa não serializa. Elas precisam ser **reconstruídas** no boot a partir de
  `aguardando` e `ultima_em` — não restauradas. Uma espera reconstruída não é
  idêntica à original: ela recomeça a contar.
- **Sessão gravada é dado pessoal em repouso.** Telefone, nome, placa e
  localização passam a existir fora do processo. O Redis é local à máquina e não
  tem porta publicada, mas isso é controle de rede, não de dado.

### A decisão de operação que isto obriga

**Se o Redis estiver indisponível na hora de gravar, a API falha o turno ou
segue em memória?**

Falhar é honesto e barulhento. Seguir é silencioso e reintroduz o problema que
esta decisão resolve, no pior momento possível.

**Decisão: seguir em memória, e registrar em log de nível `error`.** O motivo é
o domínio — recusar o turno de um pânico porque um cache caiu é pior do que
atendê-lo com risco de perder a sessão num reinício que talvez não aconteça. Mas
isso só é defensável **porque o log grita**: um erro silencioso aqui seria a
pior das três opções.

## Gatilho de revisão

- **Se o volume passar de algumas centenas de conversas simultâneas**, gravar o
  objeto inteiro a cada mutação deixa de caber, e a opção B passa à frente.
- **Se a sessão precisar ser consultada depois de encerrada**, por auditoria ou
  suporte, o lugar dela deixa de ser o Redis — e aí é a opção C, com *schema*.
- **Se o Redis sair da máquina** para um serviço gerenciado, o custo de gravação
  passa a incluir rede, e a conta do parágrafo anterior muda.

## Mais informação

- A lacuna que originou esta decisão: [auditoria, item 3](../auditoria-prototipo.md)
- Onde o estado aparece — e onde não aparece: [C4 nível 2](../architecture/c4-nivel-2-containers.md)
- Os pesos que decidiram: [matriz de decisão](../decisao-stack.md)
