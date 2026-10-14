# Rotação de credenciais

> Etapa 2 pede este procedimento "mesmo que a rotação seja simulada". A nossa
> não foi — é a mesma rotação que criou o isolamento de credencial entre dev e
> produção (17/09/2026), documentada aqui como o procedimento a seguir sempre
> que uma chave precisar trocar, por vazamento ou por rotina.

## A ordem, sempre nessa sequência

Uma chave comprometida não para de funcionar sozinha. Trocar a ordem abaixo
anula o efeito do passo seguinte.

```
1. ROTACIONAR   → gerar a credencial nova
2. INVALIDAR    → revogar/apagar a antiga no sistema que a emitiu
3. COMUNICAR    → avisar quem precisa saber (equipe, operação)
4. LIMPAR       → remover rastro da antiga de onde ela não devia estar
```

**Por que nessa ordem, e não a mais óbvia (limpar primeiro):** limpar o
histórico antes de revogar não protege nada — a chave antiga continua válida
até alguém cancelá-la no provedor. Limpar o código sem revogar é teatro: quem
já copiou a chave antes da limpeza continua com acesso.

**Regra de bolso:** trate toda credencial como comprometida se existir algum
cenário em que o repositório ficasse público amanhã e ela ainda estivesse lá.

## Evidência de execução real — 17/09/2026

Durante o trabalho de separar os ambientes de dev e produção (ver seção
[Separação de ambientes](../README.md) no README), rotacionamos credenciais de
verdade, pelos quatro passos:

| Credencial | 1. Rotacionar | 2. Invalidar a antiga | 3. Comunicar | 4. Limpar |
|---|---|---|---|---|
| Usuário MySQL de dev | `CREATE USER 'central_ia_dev'@'%'` com senha nova, escopo restrito só ao schema `central_ia_dev` | Dev deixou de usar o usuário administrativo `bahrd` (que continua existindo, mas não é mais a credencial da aplicação em dev) | Registrado nesta conversa e no commit da mudança | Senha nunca passou por commit, chat ou arquivo de texto — só por `.env.prod` na máquina, via `sed`, sem exibir o valor |
| Usuário Oracle de dev | `CREATE USER CENTRAL_IA_DEV` com privilégios mínimos (replicados de `CENTRAL_IA`, sem DBA) | Schema próprio, sem acesso ao schema de produção | Idem | Idem |

A prova de que funcionou: `docs/evidencias/` guarda o print e o log do
rollback da mesma época, e o README documenta os dois usuários distintos
(`CENTRAL_IA` × `CENTRAL_IA_DEV`, `bahrd` × `central_ia_dev`) com senha
própria cada um — confirmado por hash, nunca por valor exposto.

## Quando rotacionar, além de vazamento confirmado

- Toda chave de API de LLM (OpenRouter, Twilio, Deepgram, ElevenLabs) ao
  encerrar a disciplina — ver `docs/08-runbook-deploy.md`.
- Qualquer credencial que tenha passado por esta conversa com um assistente de
  IA, por precaução — mesmo sem evidência de vazamento.
- A cada troca de pessoa com acesso à infraestrutura (saída de alguém da
  equipe, por exemplo) — não se aplica a este projeto hoje, mas fica
  registrado como prática.

## O que este projeto ainda não automatiza

Hoje a rotação é manual, pelos passos acima. Não existe um job que rotacione
sozinho numa data fixa — é decisão consciente: rotação automática sem
alguém revisando o resultado esconde uma falha de rotação atrás de uma falsa
sensação de segurança. Fica como lacuna conhecida, não como descuido.
