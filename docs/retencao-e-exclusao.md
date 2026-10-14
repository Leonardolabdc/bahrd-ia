# Retenção e exclusão

> Etapa 2 pede "mecanismo real (cron, SQL ou cenário), e não só a intenção".
> A intenção já existia — desde 11/08/2026, no cabeçalho da própria migração
> que criou a tabela. O que faltava era o código rodar. Este documento
> descreve o mecanismo que passou a existir; o código está em
> [`workers/retencao.py`](../src/central_ia/workers/retencao.py).

## A regra

| Onde | O que guarda | Prazo | O que acontece |
|---|---|---|---|
| MySQL · `conversa` / `mensagem` | Transcrição crua — o que o cliente escreveu, de verdade | **90 dias** após `encerrada_em` | **Apagado**, não anonimizado |
| Oracle · `ocorrencia` | Resumo, desfecho, política aplicada | Retenção longa (auditoria) | Permanece |
| Redis · sessão em curso | Conversa ainda ativa | Validade do evento + 1h de folga | Expira sozinho (TTL nativo do Redis) |

## Por que separar assim

O desenho sempre tratou os dois bancos como papéis diferentes, não como
cópias um do outro:

- **MySQL é onde mora o dado pessoal bruto.** Transcrição de conversa tem
  nome, situação, às vezes um número de telefone que o cliente mencionou. É
  exatamente o tipo de dado que a LGPD manda minimizar — guardar só pelo
  tempo que serve a um propósito.
- **Oracle é a auditoria.** `ocorrencia` guarda o que decidiu o caso — não a
  conversa inteira, o resumo e o desfecho. Isso precisa sobreviver, porque é
  a prova de que o sistema tratou o evento corretamente; apagar isso também
  apagaria a capacidade de responder "por que esse caso foi fechado assim"
  daqui a um ano.

Deletar em vez de anonimizar foi escolha deliberada: anonimização levanta a
pergunta "anonimizado o suficiente?", que não tem resposta simples. Um
registro que não existe mais não tem essa ambiguidade.

## O mecanismo

Job agendado no mesmo worker `arq` que já processa a fila de eventos —
`workers/main.py::WorkerSettings.cron_jobs`, todo dia às 03h (horário de
menor tráfego medido no doc 06, para não competir por conexão com
atendimento real em curso).

```python
cron_jobs = [cron(expurgo_diario, hour=3, minute=0)]
```

A consulta só atinge conversa com `encerrada_em` preenchido — conversa em
curso, ou encerrada de forma anômala sem registrar o fechamento, nunca é
candidata. Isso é a trava contra apagar evidência de um caso que ainda pode
estar aberto.

## Testado sem tocar banco de verdade

`tests/test_retencao.py` — um dublê de conexão grava os comandos SQL
recebidos, e os testes conferem o comportamento: nada é apagado sem conversa
elegível, `mensagem` sai antes de `conversa` (ordem que respeita a
referência entre as duas tabelas), e a cláusula `encerrada_em IS NOT NULL`
está presente — a prova de que a trava de segurança não desapareceu numa
edição futura.

## O que ainda falta, de propósito

- **Expurgo manual, por enquanto** — nada no Redis Streams reexecuta o job
  se o worker cair durante a janela das 03h; ele só volta a rodar no dia
  seguinte. Para o volume desta POC, um dia de atraso não é risco.
- **Sem expurgo do Object Storage de áudio** — a POC usa voz simulada em
  produção; quando o áudio real de WhatsApp for persistido, a regra de
  *lifecycle* de 90 dias do bucket (já citada no doc 06) precisa ligar
  junto com este job, não depois.
