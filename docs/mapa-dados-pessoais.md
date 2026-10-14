# Mapa de dados pessoais

> "A primeira versão imperfeita de um mapa de dados é infinitamente melhor do
> que você não ter feito trabalho algum" — e é assim que este documento nasce:
> completo o bastante para ser útil, aberto a correção à medida que o sistema
> cresce.

## Vocabulário mínimo (LGPD)

| Termo | Quem é, neste projeto |
|---|---|
| **Titular** | O motorista ou gestor de frota que conversa pelo WhatsApp |
| **Controlador** | A Bahrd Monitoramento (fictícia) — decide o que fazer com o dado |
| **Operador** | Quem executa por conta do controlador: Twilio (mensageria), OpenRouter/Anthropic (LLM), Deepgram (transcrição de voz), ElevenLabs (síntese de voz) |

Confundir controlador com operador é o erro clássico de entrevista. Quem
**decide** tratar o dado é a Bahrd; quem **processa por fora** é cada um
desses provedores.

## O que é coletado, de onde, e por quê

| Dado | De onde vem | Sensível? | Base legal |
|---|---|---|---|
| Nome (interlocutor) | Digitado pelo cliente ou herdado do cadastro de frota | Não | Execução de contrato — identificar quem está respondendo é parte do serviço contratado pela empresa de frota |
| Telefone (WhatsApp) | Canal de origem da mensagem | Não | Execução de contrato — é o próprio meio de contato |
| Placa do veículo | Cadastro de frota | Não (mas liga a um dono) | Execução de contrato — o objeto do monitoramento |
| Endereço / coordenadas | Evento de telemetria do veículo | Não | Execução de contrato — localização é o conteúdo do alerta que está sendo tratado |
| Conteúdo da conversa (texto) | Digitado pelo cliente | Não, salvo o que o cliente mencionar por conta própria | Execução de contrato |
| Áudio de voz | Enviado pelo cliente, transcrito pelo Deepgram | Não | Execução de contrato — canal alternativo ao texto |
| CPF, telefone de terceiro, e-mail | Mencionados espontaneamente pelo cliente no meio da conversa | Potencialmente sim | Nenhuma — por isso são barrados antes de chegar ao LLM (ver `agent/pseudonimizacao.py`), não processados como dado de negócio |

**Nenhum ponto de coleta usa consentimento como base legal.** Como o Art. 7º
da LGPD deixa claro, consentimento é uma entre várias bases — e aqui não
cabe: ninguém clica em "aceito" antes de reportar que a bateria do caminhão
foi removida. A base é a execução do contrato entre a Bahrd e a empresa dona
da frota, da qual o motorista é agente.

## Transferência internacional

Toda chamada ao LLM é transferência internacional de dado, goste ou não do
termo bonito. OpenRouter, Anthropic e Google processam fora do Brasil.

| Chamada | Dado que sai | Mitigação |
|---|---|---|
| Conversa com o modelo | Texto da conversa, **sanitizado** (nome/placa/endereço viram apelido antes de sair — ver `pseudonimizacao.py`) | Base legal: execução de contrato. Mitigação técnica: dado identificador nunca atravessa a fronteira |
| Transcrição de áudio (Deepgram) | Áudio do cliente | Execução de contrato — é o próprio canal escolhido pelo cliente |
| Síntese de voz (ElevenLabs) | Texto da resposta da IA, já **reidentificado** (nome real) | Sai depois da fronteira com o LLM — não é mais "dado indo para o operador de IA", é a resposta final sendo entregue ao próprio titular, pelo canal que ele escolheu |
| Observabilidade (Langfuse) | Metadado sempre; conteúdo de conversa **nunca** em produção (`config.py::langfuse_com_conteudo`, travado no código, sem variável de ambiente que derrube isso) | Nem chega a ser transferência de dado pessoal em produção — só número (custo, latência, contagem) |

## Retenção e exclusão

Ver [`retencao-e-exclusao.md`](retencao-e-exclusao.md) para o mecanismo —
aqui só o resumo por camada:

| Onde o dado vive | Prazo | Mecanismo |
|---|---|---|
| Redis (sessão em curso) | Validade do evento + 1h de folga | TTL automático do próprio Redis (`persistence/sessoes_redis.py::_ttl_s`) |
| Oracle / MySQL (ocorrência encerrada) | 90 dias após o encerramento | Job agendado — ver doc de retenção |
| Langfuse (trace) | Conforme a retenção padrão da plataforma (metadado, sem conteúdo em produção) | Gerida pelo provedor |

## IA responsável

- **Revisão humana em decisão automatizada**: a IA só encerra um caso com um
  desfecho de uma lista fixa por tipo de evento (`domain/eventos.py`). Fora da
  lista, o caso vai para humano — não existe desfecho livre.
- **Viés**: este sistema não treina modelo próprio — usa LLMs de terceiro já
  prontos. O risco de viés é herdado do provedor, não produzido aqui; onde
  cabe mitigação nossa é não deixar o modelo decidir sozinho em caso de risco
  (pânico, coação), que é regra de domínio, não do modelo.

## O que fica de fora, de propósito

Nome de terceiro mencionado em texto livre pelo cliente ("fala com o
Roberto") não é detectado nem sanitizado — não há como fazer isso sem um
dicionário de nomes brasileiros gerando falso positivo em toda saudação.
Risco residual, aceito e registrado, não escondido.
