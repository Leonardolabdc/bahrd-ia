# ADR-002 · Publicar na Oracle Cloud, na camada gratuita permanente

- **Status:** aceita
- **Data:** 2026-09-12
- **Decide:** Leonardo Campos
- **Substitui:** —
- **Depende de:** [ADR-001 · Manter a stack herdada](0001-stack.md)

---

## Contexto e problema

O sistema roda em Docker no notebook. Precisa de um endereço público, estável,
que responda sem depender de máquina ligada — e precisa disso dentro de um prazo
fixo, sem orçamento.

## Fatores de decisão

**O ADR-001 já restringiu este espaço, e é honesto começar por aí.** Ao decidir
manter Oracle como sistema de registro, ele eliminou toda plataforma que não
oferece Oracle gerenciado — que é quase toda a lista de PaaS popular. Este ADR
não escolhe num campo aberto; escolhe no que sobrou.

Isso é consequência, não descuido. Está declarado no ADR-001 como
*"amarra a nuvem"*.

Restam quatro fatores:

1. **Hospedar Oracle e MySQL gerenciados** — imposto pelo ADR-001
2. **Custo** — o projeto não tem orçamento
3. **Sem partida a frio no caminho da requisição** — o webhook precisa responder
   na hora, sempre
4. **Dado em território nacional** — o sistema trata nome, placa e localização;
   manter tudo no país dispensa a discussão de transferência internacional

## Opções consideradas

- **A · Oracle Cloud, camada gratuita permanente** — Autonomous Database +
  MySQL HeatWave + máquina Ampere
- **B · Railway** — ~US$ 5/mês, contêiner sempre ligado
- **C · Render, plano gratuito** — R$ 0, com suspensão por inatividade
- **D · VPS barato** — máquina Linux crua, ~€4/mês

## Decisão

**Opção A — Oracle Cloud na camada gratuita permanente**, com o painel React
publicado à parte numa plataforma de borda.

| Camada | Onde | Cota | Custo |
|---|---|---|---|
| API, worker, Redis | Máquina Ampere A1 | 2 OCPU · 12 GB | **R$ 0** |
| Sistema de registro | Autonomous Database 23ai | 1 OCPU · 20 GB · 20 sessões | **R$ 0** |
| Banco operacional | MySQL HeatWave | 1 ECPU · 50 GB + 50 GB de backup | **R$ 0** |
| Painel do operador | Plataforma de borda, plano gratuito | — | **R$ 0** |
| Tráfego de saída | — | 10 TB/mês | **R$ 0** |

**Região: Brasil.** Escolhida no cadastro da conta, e **irreversível** — os
recursos gratuitos só existem na região de origem.

### Por que as outras caem

| | Por quê |
|---|---|
| **B · Railway** | Não oferece Oracle gerenciado. Cairia na Opção B do ADR-001, já rejeitada |
| **C · Render** | Mesmo problema, mais um: suspende após 15 minutos parado e leva 30 a 90 segundos para acordar. Um webhook não espera |
| **D · VPS** | Rodar Oracle em contêiner numa VPS significa administrar o banco à mão — *patching*, backup, ajuste de memória — que é exatamente o trabalho que o serviço gerenciado dispensa |

### A objeção que este ADR precisa responder

O material da disciplina recomenda **PaaS** — *"é o que você vai usar agora"* —
e a máquina Ampere é **IaaS**. Isso é contradição?

Não, e a resposta está no próprio material: *"um único projeto de IA usa várias
camadas ao mesmo tempo […] montamos a nossa pirâmide de infraestrutura"*.

A pirâmide aqui tem **três das cinco camadas em serviço gerenciado**:

```
PaaS   painel do operador, na borda
PaaS   Autonomous Database — banco gerenciado, sem trabalho de DBA
PaaS   MySQL HeatWave — idem
IaaS   máquina Ampere — API, worker e Redis em contêiner
```

O IaaS aparece onde ele compra algo que o PaaS não vende: **ausência de partida
a frio, de graça**. O material trata *warmup ping* como gambiarra e diz que, se
o app precisa estar sempre quente, o certo é pagar o plano sempre ligado. Aqui
esse plano custa zero.

## Consequências

### Boas

- **R$ 0/mês, sem prazo de validade.** Camada gratuita permanente, não teste de
  30 dias.
- **Nenhuma partida a frio no caminho da requisição.** A máquina fica ligada; a
  primeira requisição é tão rápida quanto a milésima.
- **O dado não sai do país.** Dispensa a discussão de base legal para
  transferência internacional.
- **É a arquitetura que o projeto já declarava como destino.** O trabalho
  acadêmico antecipa o plano real em vez de criar um desvio descartável.
- **A trilha de auditoria imutável continua existindo** — foi o que decidiu o
  ADR-001, e só o Autonomous Database a entrega pronta.

### Ruins — e duas são irreversíveis

- **A região é escolhida uma vez e não muda.** Errar significa refazer a conta
  do zero.
- **Máquina ociosa pode ser recuperada.** Se processador, rede e memória
  ficarem abaixo de 20% por sete dias, a Oracle pode retomar a instância. Um
  projeto acadêmico fica ocioso. A mitigação é migrar a conta para pagamento por
  uso — os recursos gratuitos continuam sem cobrança e deixam de ser recuperados
  — mas isso exige alerta de orçamento configurado **antes**.
- **Não existe rollback de plataforma numa máquina virtual.** Plataformas de
  borda guardam cada publicação e promovem uma antiga em segundos. Uma VM não
  guarda nada. O rollback aqui é reimplantar a etiqueta anterior da imagem, e
  **isso precisa estar ensaiado**, não descrito.
- **A arquitetura é ARM.** Toda imagem precisa ser construída para `linux/arm64`.
- **Teto de 20 sessões simultâneas** no banco gratuito, que obriga a reduzir o
  pool de conexões.
- **Sem suporte.** Camada gratuita não tem atendimento; o que existe é fórum.
- **Mais trabalho de operação que um PaaS.** Certificado, firewall e atualização
  de sistema passam a ser meus. É o preço da linha anterior sobre partida a frio,
  e está sendo pago conscientemente.

### Ações que esta decisão obriga

| Ordem | O quê | Por quê agora |
|---|---|---|
| 1 | **Alerta de orçamento**, antes de qualquer recurso | É o que impede uma conta gratuita de virar fatura |
| 2 | Criar a conta com **região no Brasil** | Irreversível |
| 3 | `ORACLE_POOL_MAX=6` | O teto do banco é 20 sessões |
| 4 | Build `linux/arm64` | A máquina é Ampere |
| 5 | Ensaiar o rollback e **cronometrar** | Não há rollback de plataforma para socorrer |

## Gatilho de revisão

- **Se a máquina for recuperada por ociosidade mais de uma vez**, migrar a conta
  para pagamento por uso deixa de ser opcional.
- **Se o volume passar da cota gratuita**, esta decisão vira uma decisão de
  custo, e precisa ser refeita com números reais.
- **Se o ADR-001 for revisto** e o Oracle sair da stack, todo o espaço de opções
  deste ADR se reabre — e aí Railway e Render voltam a ser candidatos legítimos.

## Mais informação

- A decisão de stack que restringiu este espaço: [ADR-001](0001-stack.md)
- Projeção de custo por serviço: [`06-custo-mensal.md`](../06-custo-mensal.md)
- Sequência de deploy e variáveis por ambiente: [`05-deploy-oci.md`](../05-deploy-oci.md)
