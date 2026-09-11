==> README.md <==
# POC IA — Central de Monitoramento Bahrd

**URA com IA generativa** para a central de monitoramento de **frotas de veículos** da Bahrd. Ela conversa com o motorista ou o gestor de frota por **ligação, áudio de WhatsApp e texto de WhatsApp**, resolve sozinha os casos que consegue confirmar e escala para o operador humano quando o caso exige julgamento, autoridade ou tem risco elevado.

## Fluxo Macro

A cor diz o papel de cada peça. **A área azul é o que tem custo por uso**, e o
tracejado é o que ainda não está no ar.

![Fluxo do atendimento, do evento ao encerramento](docs/fluxo-genaiura.png)

Três coisas que o desenho mostra e vale destacar:

**O motor de políticas decide antes de qualquer IA.** Ele é determinístico, e é
ele que manda o caso para a triagem, para o atendimento ou direto para uma
pessoa. Nenhum modelo participa dessa escolha.

**A triagem existe só para evento crítico**, e a régua é 90%: acima disso o caso
é de gente, sem conversa. Abaixo, a IA atende.

**O banco está tracejado porque ainda não foi ligado.** A ocorrência vive em
memória, e reiniciar a API apaga as conversas em curso — é a diferença entre
demonstração e sistema. O plano está em
16 · Sessões no Redis.

---

## O escopo em uma imagem

```
                    41.000 eventos / mês
                            │
        ┌───────────────────┴───────────────────┐
   ~33.000 (80%)                           8.000 (20%)
   URA determinística                      hoje 100% humano
   da Vetor                                        │
        │                            ┌─────────────┴─────────────┐
        │                        URA GenAI                   operador
        │                        (este sistema)              (os graves)
        │                            ▲
        └────────────────────────────┘
              migração gradual, evento a evento
```

**O destino é substituir a URA determinística.** Não de uma vez: começamos
direcionando **poucos eventos** para a IA, medimos, e aumentamos o volume
conforme a contenção se confirma — até que os 33.000 da Vetor passem por aqui.

O ponto de partida são os **8.000 eventos/mês** que caem inteiros nos
operadores. Ele foi escolhido porque o baseline é 100% humano: **qualquer
contenção é ganho líquido**, e uma falha nossa devolve o caso exatamente para
onde ele já estaria. É o lugar onde se erra barato enquanto se aprende.

A migração dos 33.000 vem depois, e com evidência: cada fatia só migra quando a
anterior mostrar contenção estável e zero fechamento indevido.

**Meta desta fase:** conter ≥ 50% dos 8.000 · **0** falsos fechamentos · **0**
regressão no que a Vetor ainda atende.

### O que são esses 8.000, de verdade

Conversa com o gestor da Central em 14 e 17/08/2026 corrigiu o entendimento, e a
regra é mais simples do que parecia:

```
notificação enviada
  ├─ cliente NÃO responde  →  evento fecha, zero trabalho humano
  └─ cliente RESPONDE      →  SEMPRE cai para um operador
```

**Não há filtro de complexidade.** Qualquer resposta vira toque humano, mesmo
"tá em manutenção". Desses, o gestor estima **~6.000/mês como puro registro do
retorno do cliente na placa do veículo** — o operador lê, interpreta e digita.

Ou seja: **o trabalho que sobra é digitação, não conversa** — e é exatamente o
que este sistema faz de ponta a ponta. O conjunto endereçável não é "os casos
difíceis": é **todo cliente que responde**.

> Caso extremo relatado: cliente com 500 veículos que desligam a chave geral
> diariamente gera 500 notificações tratadas à mão.

Existem **dois canais separados**. A URA de **ligação** tem menu em árvore e
atende quem telefona; a **URA Whats** notifica, pergunta e não escuta a
resposta.

---

## Stack

Duas colunas de propósito: o que **roda hoje** e para onde vai. Misturar as
duas foi o que deixou este README envelhecer sem ninguém notar.

| Camada | Hoje | Destino |
|---|---|---|
| **Back-end** | Python 3.12 · FastAPI · Pydantic v2 · arq | mesmo |
| **Front-end** | React 19 · TypeScript · Vite · CSS com design tokens | mesmo |
| **Cérebro (LLM)** | Claude Sonnet 5 via **OpenRouter** | API direta da Anthropic — cache de prompt e termos de dados |
| **WhatsApp** | **Cloud API da Meta**, número oficial da Bahrd | mesmo |
| **STT / TTS** | Deepgram Nova-3 · ElevenLabs Flash v2.5 | mesmo, ou local por LGPD ([06](docs/06-custo-mensal.md)) |
| **Telefonia** | *(não implementada)* | indefinida — GoTo descartada, ver [06](docs/06-custo-mensal.md) |
| **Observabilidade** | OpenTelemetry → Jaeger | mesmo OTLP → APM da OCI |
| **Banco de registro** | Oracle 23ai (Blockchain Table) | Autonomous Database Serverless |
| **Banco operacional** | MySQL 8.4 | HeatWave Database Service |
| **Barramento / cache** | Redis 7 | OCI Cache |
| **Infraestrutura** | Docker Compose | Oracle Cloud (OCI), região Brasil |

> ⚠️ **As ocorrências ainda vivem em memória** e somem quando a API reinicia.
> A persistência no Oracle é o que separa demonstração de sistema, e está
> pendente de conversa com a TI da Bahrd.

---

## Como rodar

Só precisa de **Docker**. Nada é instalado na máquina: Python, banco, fila e
painel sobem em contêiner.

```bash
make setup     # cria o .env a partir do .env.example
make up        # sobe a pilha
make test      # 747 testes, sem tocar rede nem API paga
```

No Windows, o mesmo pelo PowerShell: `.\dev.ps1 setup`, `.\dev.ps1 up`,
`.\dev.ps1 test`.

Depois do `make up`:

| Onde | O quê |
|---|---|
| http://localhost:5173 | painel do operador |
| http://localhost:8000/docs | a API, com o OpenAPI navegável |
| http://localhost:16686 | Jaeger, os rastros de cada atendimento |

**Uma variável precisa de valor de verdade** antes de a IA falar:
`OPENROUTER_API_KEY` no `.env`. Sem ela a pilha sobe, os testes passam e a
conversa não acontece. O resto do `.env.example` já vem com valor de
desenvolvimento.

E antes do primeiro commit, uma vez:

```bash
git config core.hooksPath .githooks
```

É a trava que impede segredo, telefone real e documentação interna de entrarem
por descuido. Ela é local e **não vem no clone**, então cada pessoa liga a sua.

Detalhes de cada serviço, paridade com a OCI e problemas conhecidos estão em
[04 · Ambiente Docker](docs/04-ambiente-docker.md).
---

## Organização do projeto

```
bahrd-ia/
├── src/central_ia/        o código da aplicação
├── web/                   painel do operador (React + Vite)
├── tests/                 747 testes
├── prompts/               os textos que definem como a IA fala
├── docs/                  23 documentos em .md
├── docker/                imagens e composição dos contêineres
├── infra/                 configuração de servidor e OCI
├── migrations/            evolução do banco (Alembic)
└── .githooks/             trava de segredo, ativada com core.hooksPath
```

Dentro de `src/central_ia/`:

| Pasta | O que faz |
|---|---|
| **`domain/`** | as regras — catálogo de eventos, limiares, desfechos permitidos |
| **`agent/`** | a IA conversando — turno, triagem de pânico, esforço, vigilância |
| **`api/`** | rotas HTTP — webhooks de WhatsApp, painel, saúde, mídia |
| **`integrations/`** | adaptadores — Meta, Twilio, OpenRouter, Anthropic, Deepgram, Bahrd |
| **`orchestration/`** | o pipeline: evento → política → IA → desfecho |
| **`ports/`** | os contratos — o que um LLM ou um canal precisa saber fazer |
| **`persistence/`** | banco de dados |
| **`workers/`** | tarefas em segundo plano — esperas e retomadas |
| **`observability/`** | logs estruturados e rastros (OpenTelemetry) |

**A regra que sustenta o desenho:** `domain/` não conhece ninguém. Ele define
as regras; `integrations/` implementa os contratos de `ports/`. É por isso que
trocar Twilio por Meta, ou Claude por Gemini, foi variável de ambiente — não
reescrita.

---

## Documentação

| Documento | Conteúdo |
|---|---|
| **[02 · Plano de execução](docs/02-plano-execucao-backend.md)** | Decisões de arquitetura, justificativa de cada escolha, integração com o GoTo Connect (3 modelos), **estratégia Docker-first**, modelo de dados Oracle + MySQL, configuração da camada de IA, orçamento de latência de voz, guardrails, **front-end React**, roadmap de 6 sprints e custos |
| **[04 · Ambiente Docker](docs/04-ambiente-docker.md)** | Como subir a pilha local, o que cada serviço vira na OCI, as decisões não óbvias (sondas de saúde, schema sem DBA, os dois deltas para o ADB-S), migrações, matriz de paridade e problemas conhecidos |
| **[05 · Deploy na OCI](docs/05-deploy-oci.md)** | Publicação no OCIR, deploy de fumaça no ADB-S, tabela de variáveis por ambiente, sequência de deploy e rollback, e o que ainda depende de terceiros |
| **[06 · Custo mensal](docs/06-custo-mensal.md)** | Projeção para 8.000 e 41.000 eventos, por serviço, com o grau de confiança de cada linha |
| **[07 · Segurança](docs/07-seguranca.md)** | O que já está protegido, o que fica para a saída da POC com o gatilho de cada item, e o que decidimos **não** fazer — **consulte antes de implementar segurança** |

---

## Detalhe de cada um

### 1 · Eventos reais

Hoje a conversa começa quando alguém digita `bateria` no WhatsApp. No MVP, o
evento vem do sistema da Bahrd.

**O que pedimos:** que o sistema envie o evento para um endereço nosso — o
mesmo POST que a URA Whats já dispara hoje, apontado também para nós. O gestor
da Central confirmou que consegue redirecionar e **filtrar por tipo**, o que
permite começar por um evento só.

**Antes disso, o mais barato:** **5 a 10 payloads de exemplo** em JSON. Sem
eles, o endpoint é adivinhação. O tradutor do formato da Bahrd **já existe**
(`integrations/rastreamento/link.py`), escrito contra um export real — falta
confirmar que o webhook manda no mesmo formato.

**Por onde começar:** remoção de bateria. Playbook maduro, erro barato. Pânico
por último.

### 2 · API de escrita no sistema interno

É o item que transforma "a IA conversou bem" em "o operador não digitou".

A regra de hoje, confirmada pelo gestor da Central em 17/08/2026:

```
cliente NÃO responde  →  evento fecha sozinho, zero trabalho humano
cliente RESPONDE      →  SEMPRE cai para um operador
```

Não há filtro de complexidade — qualquer resposta vira toque humano. Desses,
**~6.000/mês são puro registro do retorno na placa do veículo**: o operador lê,
interpreta e digita.

A IA já entende e classifica. Falta poder **escrever onde eles escrevem**.

**O que precisamos saber:** existe API? Que campos ela espera? Aceita texto
livre ou código? O sistema é da própria Bahrd, então não depende de fornecedor.

> **Consequência para a medição:** o denominador da contenção não é "casos
> difíceis" — é **todo cliente que responde**. Isso torna a métrica direta:
> de cada 100 respostas, quantas fecharam sem operador.

### 3 · Chave de LLM

O cérebro. Sem ela a IA não fala.

#### Qual modelo

O que roda hoje é o **Claude Sonnet 5**. Custo por mês, nos três recortes de
volume da Central (ver 22):

| Modelo | 2.250 conversas | 10.000 tratativas | 43.000 eventos |
|---|---|---|---|
| **Claude Sonnet 5** — roda hoje | **R$ 210** | **R$ 935** | **R$ 4.020** |
| Claude Haiku 4.5 | R$ 105 | R$ 468 | R$ 2.010 |
| Gemini 2.5 Flash | R$ 96 | R$ 426 | R$ 1.833 |
| DeepSeek v3.1 | R$ 71 | R$ 317 | R$ 1.363 |
| Gemini 2.5 Flash Lite | R$ 29 | R$ 127 | R$ 548 |

Base: **US$ 0,017 por atendimento** no Sonnet 5, medido em 54 conversas, com
82% da entrada vindo do cache. Preços puxados da API da OpenRouter em
02/09/2026. Detalhe em [06 · Custo mensal](docs/06-custo-mensal.md).

> ⚠️ **O cache decide mais que o preço de tabela.** O adaptador só manda
> `cache_control` para modelos `anthropic/`; nos outros, cada turno paga os
> ~20 mil tokens de prompt inteiros. Por isso o DeepSeek, 8× mais barato por
> token, sai só 3× mais barato na prática.

> ⚠️ **A maior economia da tabela é R$ 182/mês no escopo real.** Uma hora de
> trabalho de gente, contra o sistema decidir se um alarme de roubo é falso.
> **Trocar de modelo é o item de menor retorno da lista** — e o caso que exige
> julgamento é o **pânico**. Se for testar um mais barato, testar por ali
> primeiro: se segurar o caso difícil, os fáceis vêm de graça.

#### Por onde comprar

| | Taxa | Cache de prompt | Registro de conversa |
|---|---|---|---|
| **Anthropic direta** | — | ✅ | contrato direto; não treinam com entrada de API |
| **Google AI Studio** — grátis | — | ✅ | ⛔ **"content used to improve our products"** |
| **Google AI Studio** — pago | — | ✅ | não usam para melhorar produtos |
| **OpenRouter** | **+5,5%** na compra de crédito | ✅ | zero registro por padrão |

**A OpenRouter não marca preço de token** — repassa a tabela do fornecedor e
cobra **5,5% na compra de crédito**: ~US$ 83/mês sobre o Claude no volume cheio.

> ⛔ **O plano grátis do Google não serve para evento real.** No gratuito, o
> conteúdo é usado para melhorar os produtos deles — nome do motorista, placa,
> localização, o áudio de um pânico. Vincular cobrança sai do gratuito na hora e
> resolve. Para demonstração com dado fictício, serve.

**Manter a OpenRouter enquanto for comparação de modelo**, e ir direto no
fornecedor escolhido quando a voz entrar: o salto de rede a mais custa latência,
e latência é o que decide se a conversa por voz soa natural. Detalhe da conta e
dos outros critérios em [06 · Custo mensal](docs/06-custo-mensal.md).

> **A economia de US$ 700/mês do cache já está capturada.** A OpenRouter aceita
> `cache_control` para modelos Claude igual à API direta, e o nosso adaptador
> envia o campo desde 19/08/2026: o breakpoint vai no último bloco de sistema,
> com `ttl` de 1 h, em
> [`openrouter.py`](src/central_ia/integrations/llm/openrouter.py).
>
> Medido num turno real de 28/08: **16.517 dos 20.230 tokens de entrada vieram
> do cache**, 82%. O custo medido por turno de conversa é de **US$ 0,0093**, e
> por atendimento completo, **US$ 0,017**.

### 4 · Deepgram — o ouvido

Transcreve a nota de voz que o motorista manda. Sem ele, a IA só entende texto
— e motorista dirigindo manda áudio.

Português do Brasil confirmado, a partir de 8 kHz (qualidade de telefonia).
Tem camada gratuita suficiente para teste.

### 5 · ElevenLabs — a voz

Transforma a resposta da IA em áudio. Quem manda áudio espera áudio de volta.

O plano gratuito **não libera voz brasileira por API** — hoje a voz tem sotaque
estrangeiro. São **US$ 5/mês** para resolver, e é a diferença entre soar como a
central da Bahrd e soar como robô de tradutor.

> No volume de 41.000 eventos essa linha vira ~R$ 9.000/mês e passa a ser o
> segundo maior custo do sistema. Aí vale avaliar voz local — ver
> [06 · Custo mensal](docs/06-custo-mensal.md).

### 6 · Número na API oficial do WhatsApp

Hoje rodamos no **sandbox do Twilio**: funciona, mas é número de teste e o
cliente precisa se cadastrar antes de receber mensagem. Não serve para produção.

**O que precisamos:**

| | |
|---|---|
| Um número novo, **nunca usado no WhatsApp comum** | se já foi usado no app, apagar a conta antes |
| Empresa verificada na Meta | leva dias — **comece por aqui**, não depende do número |
| Nome de exibição aprovado | é o que o motorista vê: *"Bahrd Monitoramento"*, não um número |
| Modelo de mensagem aprovado | a notificação inicial precisa ser template |

**Vale conferir antes:** a URA Whats da Vetor provavelmente já usa a API
oficial. Se a conta (WABA) estiver **no nome da Bahrd**, boa parte disso já
existe e é só apontar o webhook. Se estiver no nome da Vetor, precisa migrar —
e essa conversa é melhor ter antes de anunciar a substituição.

### 7 · Tronco SIP + número brasileiro novo

Para o motorista **sem internet**. A cobertura de voz no Brasil é mais ampla
que a de dados, e é justamente em rodovia que a diferença aparece — sem dados,
ele não recebe nem a mensagem.

**O critério é um só:** o provedor entrega **áudio bidirecional em tempo real**
(WebSocket ou SIP)? Sem isso a IA não entra na chamada. Isso elimina a maior
parte do que se vende como telefonia corporativa, incluindo boa parte do que a
GoTo oferece.

| Provedor | Situação | Observação |
|---|---|---|
| **Twilio Media Streams** | ✅ verificado | já somos clientes; "agentes de IA" é caso de uso oficial |
| **LiveKit SIP** | ✅ verificado | feito para agente de voz; número próprio ou tronco de terceiro |
| **Telnyx** | provável | rede própria, preço melhor, boa reputação de suporte |
| **Vonage** | provável | WebSocket de áudio maduro |
| **Zenvia** | **confirmar** | brasileira, suporte em português — não consegui verificar o áudio em tempo real |

**Sugestão:** começar pelo **Twilio**, não por ser o melhor ou o mais barato,
mas porque a conta já existe e o time conhece o padrão. Cotar Telnyx e Zenvia
em paralelo.

**Número brasileiro exige CNPJ e endereço comprovado** — para a Bahrd é
papelada, não barreira.

> ⚠️ **O número do WhatsApp não serve para voz.** Número registrado na API do
> WhatsApp fica dedicado a ela. São dois números, dois contratos.

**O que pedir na cotação**, para os números virarem orçamento:

1. Mensalidade do número (DID) brasileiro
2. Minuto de entrada e de saída, separados
3. Chamadas simultâneas incluídas no plano
4. Se entregam **SIP** ou só API própria — é o que decide se dá para usar

---

### 8 · LiveKit — a camada de mídia

O tronco entrega a chamada; **o LiveKit é o que põe a IA dentro dela** — recebe
o áudio do motorista ao vivo, manda para a transcrição e devolve a voz na mesma
chamada. Sem essa camada, o item 7 é só uma linha telefônica tocando.

**Hoje custa R$ 0.** O `livekit-server` é Apache 2.0 inteiro — não é open core,
e não há recurso bloqueado no auto-hospedado. Dá para testar por navegador, sem
telefone e sem contrato, antes de comprar qualquer coisa.

Em produção há dois caminhos:

| | Custo | O que pesa |
|---|---|---|
| **LiveKit Cloud** | US$ 50 (8.000 ev) · US$ 164 (41.000 ev) | ⚠️ para em **20 chamadas simultâneas**; acima disso, US$ 500 |
| **Auto-hospedado na OCI** | ~R$ 500 a 1.500/mês | IP público, **UDP 50000–60000**, certificado assinado, Network Load Balancer |

**São da mesma ordem de grandeza.** A escolha é sobre quem administra dez mil
portas UDP e renovação de certificado, não sobre economia — a menos que a
parceria com a Oracle cubra a Compute, aí muda.

Duas coisas ainda não confirmadas: **não há preço publicado para número
brasileiro** na tabela deles (só EUA), e **não está claro se cobram transporte
SIP sobre tronco de terceiro** — que é exatamente o nosso caso. Os US$ 164 são
piso, não teto. Detalhe em 09 · Voz.

---

## Ordem sugerida

| Quando | O quê | Por quê |
|---|---|---|
| **Esta semana** | payloads de exemplo (1) · verificação da empresa na Meta (6) | destravam tudo e não dependem de compra |
| **Em seguida** | chave da Anthropic (3) · contas de voz (4, 5) | baratos, imediatos |
| **Depois** | webhook real (1) · API de escrita (2) | o ciclo completo |
| **Por último** | provedor de voz (7) · camada de mídia (8) | os ~8.000 são WhatsApp, não ligação |

---

## O que **não** estamos pedindo

**Oracle Cloud, LiveKit em produção, GoTo.** Nada disso é necessário para o MVP
funcionar com evento real. Entram quando a POC virar sistema.

**Nada da Vetor.** Só a informação de quem é dona da conta do WhatsApp — e essa
é a Bahrd que consulta, no Meta Business Manager.

---

## Onde cada coisa mora

Os pedidos do gestor da Central (17/08/2026) mapeados. A regra por trás:
**compre o que é obrigação, construa o que é diferencial.** Caixa de entrada
todo helpdesk tem; auditoria de decisão de IA, nenhum.

Três destinos possíveis:

* **Plataforma** — o sistema de atendimento, seja Chatwoot, a própria Vetor ou
  outro. O que importa é a fronteira, não a marca.
* **Nosso painel** — o que construímos nesta POC.
* **A IA** — não é tela nenhuma; é o motor.

| O quê | Onde | Observação |
|---|---|---|
| Conversa com o cliente | **Plataforma** | canal e histórico · abrir do nosso painel: 10 |
| Fila do que a IA escalou | **Plataforma** | |
| Atribuição em rodízio | **Plataforma** | trava contra dois operadores no mesmo caso |
| Busca por placa, telefone, nome, data | **Plataforma** | liberável ao operador, não só ao gestor |
| Filtros, SLA, tempo de espera | **Plataforma** | |
| Passagem de turno | **Plataforma** | |
| Nota interna, resposta pronta | **Plataforma** | |
| Login por pessoa, permissão por papel | **Plataforma** | a POC hoje usa token compartilhado |
| Status de entrega da mensagem | ⚠️ **quem dispara** | ver condicional abaixo |
| Registro para contestação | ⚠️ **quem dispara** | ver condicional abaixo |
| Lista de retornos · **varrer um a um** | **desaparece** | a IA processa; ninguém precisa varrer |
| Lista de retornos · **provar envio e resposta** | ⚠️ **quem dispara** + nosso painel | contestação precisa dos dois lados |
| Lista de retornos · **medir quantos fecharam sozinhos** | **Nosso painel** | é a contenção |
| Por que a IA decidiu | **Nosso painel** | faixa de probabilidade, evidência da triagem |
| Trilha de auditoria | **Nosso painel** | política, versão de prompt, evidência, custo |
| Prova à prova de adulteração | **Nosso painel** | Blockchain Table do Oracle |
| Contenção | **Nosso painel** | quantos fecharam sozinhos, com qual desfecho |
| Custo por evento | **Nosso painel** | |
| Equipamentos com alta probabilidade de defeito | **Nosso painel** | rastreador que dispara repetido |
| Desfecho e a lista branca que o autorizou | **Nosso painel** | o que a IA podia concluir, e o que concluiu |
| **Ler e classificar o retorno do cliente** | **A IA** | os ~6.000/mês — **nenhuma tela resolve** |
| **Escrever na placa do veículo** | **A IA** | depende do item 2 desta página |
| Falar com vários contatos em paralelo | **A IA** | a URA não consegue |
| Espera e retomada | **A IA** | |
| Triagem de pânico | **A IA** | |

### Sobre a lista de retornos

É a tela mais usada da operação hoje (`geral/list-retornos.php`, login
**Ativo**): notificação enviada e resposta do cliente lado a lado, filtrável e
exportável. Ela aparece em três linhas da tabela porque tem três funções, e só
uma delas sobrevive à automação.

A principal — varrer dezenas de retornos por turno — existe **porque um humano
processa cada um**. Automatizado o processamento, a bancada perde a função.

**Na transição ela continua necessária**: enquanto a IA cobrir só um tipo de
evento, os operadores precisam dela para os demais. Migrar de plataforma nesse
período os deixaria pior antes de melhor.

> 💡 **Ela tem botão `Baixar`.** Exportar esse histórico é a forma mais barata
> de medir quantos casos a IA fecharia sozinha — com dado real, sem depender de
> ninguém desenvolver nada.

### ⚠️ Duas linhas dependem de quem dispara

**Contestação** (*"o cliente diz que não recebeu"*) e **status de entrega** só
existem onde o envio acontece.

Se o disparo continuar na Vetor e só as respostas vierem para nós, o caso em que
o cliente **não respondeu** não terá registro nenhum do nosso lado — e é
justamente o caso da contestação.

É o argumento mais forte para a arquitetura combinada: **a Bahrd manda o evento,
nós notificamos**. Aí todo envio tem registro nosso, respondido ou não, e a
contestação se resolve com um registro que ninguém pode editar — nem nós.

### Uma observação de prioridade

Cinco dos seis pedidos do gestor são sobre a **operação humana**, e todos têm
solução pronta. O que sobra — ler o retorno e registrar na placa — é o volume
real, não se resolve com tela, e depende de nós.

Vale garantir que a discussão de plataforma não atrase a **API de escrita**, que
é o que faz os outros cinco encolherem.

---

## Quatro configurações nossas, antes do primeiro evento real

Nenhuma é código. Todas são fáceis de esquecer justo no dia em que mais
importam.

| Variável | Está | Precisa | Por quê |
|---|---|---|---|
| `BAHRD_WEBHOOK_HMAC_SECRET` | `dev-hmac-…` | segredo real da TI | sem ele, qualquer um forja um evento |
| `LANGFUSE_ENVIAR_CONTEUDO` | `true` | `false` | manda nome, placa e endereço do cliente para a nuvem |
| `ESCALONAMENTO_HUMANO_ATIVO` | `false` | `true` | hoje a IA encerra tudo, registrando o motivo pelo qual teria escalado |
| `PANICO_AUTONOMO` | `true` | decisão de operação | a IA pode encerrar sozinha um pânico que ela classificou como alarme falso |

O valor de desenvolvimento do HMAC se chama `dev-hmac-nao-usar-em-producao`
justamente para não passar despercebido numa revisão.

⚠️ **O `PANICO_AUTONOMO` é a única exposição conhecida do sistema**, e está
ligado de propósito: é o que permite medir a qualidade da triagem de pânico
contra eventos reais antes de decidir qualquer coisa sobre supressão
automática. Desligar é uma linha; a decisão é da operação, não do código.

---

## Estado hoje

**Funciona ponta a ponta, com evento real e celular de verdade:**

```
evento da Bahrd → template com mapa → botões → conversa → desfecho → painel
```

Testado à mão, em celular de verdade: notificação com cartão de mapa, os dois
botões do template, os quatro caminhos de causa, o pedido de atendente humano e
o encerramento com o desfecho registrado.

**E testado em leva contra os prompts reais**, em 28/08/2026: 54 conversas
escritas como um motorista escreve, com erro de digitação, caixa alta, gíria,
mensagem picada, cliente irritado e tentativa de injeção de prompt. O caminho
exercitado é o de produção inteiro, do payload da Bahrd ao desfecho e à
tratativa, com o cliente da Meta trocado por um dublê: nenhuma mensagem sai,
nenhum template é disparado.

Aquela leva achou **catorze defeitos**, todos corrigidos e com teste de
regressão citando a conversa que os produziu. Os três piores davam a mesma
classe de erro, e é a que mais importa num sistema que a Central vai usar sem
ficar olhando: **a conversa terminava bonita e nada acontecia do outro lado.**

**O que ainda não existe:**

| | Onde |
|---|---|
| Escrita no sistema da Bahrd | bloqueada na TI deles |
| Persistência das conversas | ainda em memória — 16 |
| Botões do pânico | decisão dos gestores — 17 |
| Voz por telefone | sem provedor definido — 09 |

**Qualidade:** 747 testes, sem tocar rede, banco nem API paga. CI com lint,
testes e varredura de segredo no histórico. Trava de segredo antes de cada
commit — `git config core.hooksPath .githooks`.

> **Retomando o projeto?** 21 · Atualização do projeto
> tem a lista inteira do que está em aberto, agrupada por quem precisa decidir:
> nós, os gestores, ou a TI da Bahrd.
