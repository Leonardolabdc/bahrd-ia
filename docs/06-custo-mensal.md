# 12 · Quanto custa por mês

Dois cenários: **8.000 eventos** (os que hoje escapam da URA e caem no operador)
e **41.000 eventos** (o volume inteiro). Oracle fora da conta, por parceria.

> **Um número é medido; os outros são estimativa.** O custo do modelo sai da
> resposta do próprio provedor, ocorrência por ocorrência. Os demais vêm das
> tabelas públicas de cada fornecedor e **precisam ser confirmados** antes de
> virar orçamento — preço de WhatsApp e de voz muda com frequência.

---

## Cenário 1 · WhatsApp em texto — é o que roda hoje

| Serviço | Por evento | 8.000 eventos | 41.000 eventos |
|---|---|---|---|
| Claude — **medido, com cache** | US$ 0,0211 | US$ 169 | US$ 865 |
| WhatsApp (Meta) · 1 template | US$ 0,006 | US$ 49 | US$ 253 |
| **Total** | **~US$ 0,027** | **~US$ 218** | **~US$ 1.118** |

≈ **R$ 1.200/mês** para 8.000 · ≈ **R$ 6.100/mês** para 41.000

> ⚠️ **Corrigido em 01/09/2026, e a conta caiu 37%.** Esta tabela trazia o
> Claude a **US$ 0,037** por evento, e o total em R$ 1.900 / R$ 9.700. Aquele
> número era de antes de o `cache_control` funcionar, e ainda usava o preço
> antigo do Sonnet 5.
>
> A linha de agora é **medida em atendimento real**, não estimada: a memória do
> cálculo está em *Custo por evento · estimado e medido*, mais abaixo. O harness
> de roteiros, em 54 conversas, mediu ainda menos, **US$ 0,017**. Mantive o
> US$ 0,0211 aqui porque ele veio de um atendimento de WhatsApp de verdade e é
> o mais conservador dos dois.

---

## Cenário 2 · Com áudio no WhatsApp

Soma ao cenário 1, contando 1 áudio recebido e 3 respostas por atendimento.

| Serviço | Por evento | 8.000 eventos | 41.000 eventos |
|---|---|---|---|
| Deepgram (transcrição) | ~US$ 0,01 | ~US$ 80 | ~US$ 410 |
| ElevenLabs (voz) | ~US$ 0,04 | ~US$ 320 | ~US$ 1.640 |
| **Total com áudio** | **~US$ 0,093** | **~US$ 745** | **~US$ 3.820** |

≈ **R$ 4.100/mês** para 8.000 · ≈ **R$ 21.000/mês** para 41.000

---

## Cenário 3 · Com telefonia

Só faz sentido para o que **precisa** de ligação — na prática, uma fração. A
conta abaixo é sobre **20%** dos eventos, com 2 minutos de chamada.

São **duas contas separadas**, e é útil não confundir: o tronco é o minuto da
operadora, comprado em real; o LiveKit é a camada que põe a IA dentro da
chamada. Sem ele, o tronco é só uma linha telefônica tocando.

| Serviço | Por chamada | 1.600 chamadas | 8.200 chamadas |
|---|---|---|---|
| Tronco SIP (2 min) | ~US$ 0,08 | ~US$ 130 | ~US$ 660 |
| LiveKit (camada de mídia) | assinatura | ~US$ 50 | ~US$ 164 |
| **Soma da telefonia** | | **~US$ 180** | **~US$ 824** |

**Total acumulado** — cenário 1 + 2 + 3:

| | 8.000 eventos | 41.000 eventos |
|---|---|---|
| **Tudo somado** | **~US$ 798** | **~US$ 3.992** |
| | ≈ **R$ 4.400/mês** | ≈ **R$ 22.000/mês** |

*Trazia US$ 925 e US$ 4.644 até 01/09/2026. A diferença é só a correção do
cenário 1, que passou a usar o custo medido do modelo.*

Telefonia para **todos** os eventos multiplicaria isso por cinco e não se
justifica: WhatsApp resolve a maioria por uma fração do preço.

> ⚠️ **O LiveKit pode triplicar sem o volume mudar.** O plano para em **20
> chamadas simultâneas**. No volume de 41.000, se passar disso, salta de
> US$ 164 para **US$ 500** — é a simultaneidade que decide, não o total de
> minutos. Auto-hospedar na OCI custa a mesma ordem de grandeza (~R$ 500 a
> 1.500/mês). Ver 09 · Voz.

**A mensalidade do número brasileiro não está na conta** — dezenas de reais por
mês, ainda não cotada. Não muda o total, mas falta.

---

## O que mexe mais na conta

**1 · Cache de prompt — ✅ implementado em 19/08/2026.**
Os quatro blocos de sistema somam ~5.500 tokens e eram reprocessados a cada
turno. Agora o breakpoint vai no último bloco
([`openrouter.py`](../src/central_ia/integrations/llm/openrouter.py),
função `_sistema`), e eles são relidos a **10% do preço** a partir do segundo
turno. O custo do modelo cai de **US$ 0,037 para ~US$ 0,02** por evento —
**~US$ 700/mês** no volume de 41.000, e menos latência de quebra.

> **Não dependia de trocar de fornecedor.** A OpenRouter aceita `cache_control`
> igual à API direta e ainda fixa o roteamento no mesmo provedor para aumentar
> o acerto. O que faltava era o nosso adaptador enviar o campo.

Duas decisões registradas no código:

* **`ttl` de 1 h**, não os 5 min padrão. A escrita custa 2×, mas 5 min morre
  entre uma ocorrência e outra; 1 h atravessa, e no volume da Bahrd há conversa
  o tempo todo.
* **Só modelos `anthropic/` recebem o campo.** Gemini faz cache implícito
  sozinho. Isso preserva a troca de modelo por variável, que é o motivo de a
  OpenRouter estar no projeto.

⚠️ **Como saber se está pegando:** o adaptador agora lê
`prompt_tokens_details.cached_tokens` para `uso.tokens_cache_leitura`. No
**segundo turno** de uma conversa esse número tem de ser **> 0**. Se vier `0`,
o breakpoint quebrou — quase sempre porque algo variável (data, nome, id de
ocorrência) entrou num bloco de sistema. Cache quebrado **não dá erro**: tudo
continua funcionando e só a fatura muda.

### O cache sobrevive à troca de modelo

Pergunta que apareceu ao decidir manter a OpenRouter: **trocar de modelo perde
o cache?** Não — só a Anthropic exigia código nosso.

| Provedor | Como funciona | Leitura custa |
|---|---|---|
| **Anthropic** | precisa de `cache_control` | **0,1×** |
| DeepSeek | automático | 0,1× |
| OpenAI | automático | 0,25–0,5× |
| **Gemini** | implícito (2.5+) | 0,25× |
| Grok · Moonshot | automático | 0,25× |
| Groq | automático | 0,5× |

> **Por que o Gemini fica de fora do `cache_control`.** Ele aceita os dois
> modos, mas o explícito cobra **taxa de armazenamento de 5 min** enquanto o
> implícito é de graça. Mandar o campo seria pagar por algo que ele já faz sem
> cobrar. Verificado em 19/08/2026.

O Claude é o que mais desconta na leitura (0,1×), então o cache encurta a
distância dele para o Gemini — sem eliminá-la.

**2 · A voz sintética é o segundo maior custo, e é opcional.**
Responder em texto onde o motorista pode ler elimina a linha da ElevenLabs sem
perder atendimento. O áudio vale a pena para quem está dirigindo — não para
todo mundo.

**3 · O WhatsApp deixou de ser o maior item — correção de 19/08/2026.**
A estimativa anterior era US$ 400 / US$ 2.050, feita sobre o modelo antigo da
Meta, que cobrava por **conversa**. Desde julho de 2025 é **por mensagem, e só
template é cobrado** — a resposta do motorista dentro da janela de 24 h é
grátis. No nosso fluxo isso é **um template de utilidade por ocorrência**
(R$ 0,034), e a linha caiu **8×**.

O que restou de incerto é **a categoria, não o preço**: quem classifica o
template é a Meta. Aprovado como *marketing* em vez de *utilidade*, custa **9×
mais** (R$ 0,3125). Detalhe em 17 · WhatsApp Cloud
API.

**4 · O Twilio soma, não substitui.**
Ele cobra **US$ 0,005 por mensagem, entrando e saindo**, por cima da tarifa da
Meta. Numa conversa de 8 mensagens são US$ 0,04 por atendimento — mais que a
própria tarifa da Meta. No volume de 41.000, o acréscimo passaria de **US$
1.600/mês** para entregar o que a Cloud API entrega direto. **Sair do Twilio é
economia, não só arquitetura.**

---

## Alternativa de modelo

> **Reescrito em 02/09/2026, com preços puxados da API da OpenRouter e o custo
> por atendimento medido em conversa real.** A versão anterior comparava com o
> `gemini-3.1-pro`, que **não existe mais** no catálogo, e usava uma base sem
> cache que não correspondia ao que a gente paga.

### Os três volumes, e o que cada um significa

A escolha de modelo muda pouco na conta enquanto o escopo for o que existe. Por
isso a tabela traz os três recortes: quem lê decide qual defender.

```
43.000  tudo que o sistema da Bahrd gera por mês
        a maior parte nunca chega em ninguém
   ↓
10.000  o que a Central trata À MÃO hoje       ← é o trabalho que existe
   ↓
 2.250  o que sobra tirando os encaminhamentos para grupo
        e o cavalo e carreta — ver 22
```

| Modelo | 2.250 conversas | 10.000 tratativas | 43.000 eventos |
|---|---|---|---|
| Gemini 3.8 Flash | R$ 215 | R$ 957 | R$ 4.115 |
| **Claude Sonnet 5** — roda hoje | **R$ 210** | **R$ 935** | **R$ 4.020** |
| Claude Haiku 4.5 | R$ 105 | R$ 468 | R$ 2.010 |
| Gemini 2.5 Flash | R$ 96 | R$ 426 | R$ 1.833 |
| DeepSeek v3.1 | R$ 71 | R$ 317 | R$ 1.363 |
| Gemini 2.5 Flash Lite | R$ 29 | R$ 127 | R$ 548 |

Câmbio de R$ 5,50. Base: **US$ 0,017 por atendimento no Sonnet 5**, medido em 54
conversas, com ~20.230 tokens de entrada e ~600 de saída por turno e 82% da
entrada vindo do cache.

⛔ **O Gemini 3.8 Flash aparece no topo, e não é erro de conta.** Ele é 2,7x mais
barato que o Sonnet por token e ainda assim sai **mais caro** no mês. O motivo é
o mesmo que vale para as outras linhas não-Anthropic — a tabela as calcula sem
cache — só que aqui ele inverte o resultado em vez de encolher a vantagem: o
Sonnet paga $0,20 em 82% da entrada, e o 3.8 Flash, nesta base, paga $0,75 na
entrada inteira.

Se o cache explícito fosse habilitado para não-Anthropic, a mesma linha cairia
para **R$ 77 · R$ 342 · R$ 1.472** — aí sim 2,7x abaixo do Sonnet.

⚠️ **As duas pontas são limites, e o número real está entre elas.** A tabela de
*Preço do cache por provedor*, mais acima, registra que o Gemini 2.5+ faz cache
**implícito**, a 0,25× — sem código nosso. Se isso valer através da OpenRouter,
o custo verdadeiro fica abaixo de R$ 957 mesmo sem mexer no adaptador. **Não foi
medido**, e é o primeiro número a levantar se este modelo for testado: uma
conversa de três turnos com o `usage` da resposta na mão responde.

### Preço por milhão, e a coluna que decide a conta

| Modelo | Entrada | Saída | Leitura de cache |
|---|---|---|---|
| Claude Sonnet 5 | $2,00 | $10,00 | $0,20 |
| Claude Haiku 4.5 | $1,00 | $5,00 | $0,10 |
| Gemini 3.8 Flash | $0,75 | $3,75 | $0,075 |
| Gemini 2.5 Flash | $0,30 | $2,50 | $0,03 |
| DeepSeek v3.1 | $0,25 | $0,95 | $0,13 |
| Gemini 2.5 Flash Lite | $0,10 | $0,40 | $0,01 |

Preços lidos em `https://openrouter.ai/api/v1/models` em 09/09/2026, que é o
roteador por onde os cinco passam. O 3.8 Flash entrou no catálogo em
**02/09/2026** — tem uma semana. Contexto de 1M em todos os Gemini, e o 3.8
aceita **áudio nativo na entrada**, o que hoje é serviço à parte (Deepgram,
R$ 0,06 por evento).

⚠️ **A terceira coluna importa mais que as duas primeiras, e o adaptador só a
usa na Anthropic.** O `openrouter.py` manda `cache_control` apenas para modelos
com prefixo `anthropic/`. Fora deles, cada turno paga os ~20 mil tokens de
prompt **inteiros**, e a vantagem de preço encolhe:

```
DeepSeek v3.1   8x mais barato por token,  SEM cache  →  3x mais barato na prática
Haiku 4.5       2x mais barato por token,  COM cache  →  2x mais barato na prática
Gemini 3.8      2,7x mais barato por token, SEM cache →  2% mais CARO na prática
```

⚠️ **A terceira linha é a que mostra o tamanho do problema.** Nas outras duas a
falta de cache encolhe a vantagem; no 3.8 Flash ela inverte o sinal, e a tabela
de cima passa a recomendar o contrário do que recomendaria. Enquanto a condição
de prefixo estiver ali, **nenhuma comparação com modelo caro é justa** — e é
justamente o modelo mais novo, que se quer testar, o mais penalizado por ela.

Os quatro não-Anthropic **têm** preço de cache publicado. Habilitá-lo é mudar uma
condição no adaptador, não reescrever nada — e é o que faria a comparação ser
justa de verdade.

### O que essa tabela não diz, e é o que decide

A maior economia da tabela, no escopo real, é de **R$ 182 por mês**. Uma hora de
trabalho de gente.

Do outro lado está o sistema decidindo se um alarme de roubo é falso, com regras
finas que modelo barato erra primeiro:

```
diga "manutenção", nunca "oficina" — a menos que o cliente diga oficina
repita a data com as palavras dele: "até quarta então"
a frase da autorização, quase ao pé da letra
"Bahrd Monitoramento" sempre inteiro, nunca só "Bahrd"
não cumprimente duas vezes, e nunca no fim
```

**Trocar de modelo é o item de menor retorno da lista.** No mesmo doc 22 estão
os 6.000 encaminhamentos que talvez saiam com uma regra de cadastro, e no
21 as sessões no Redis, que hoje apagam
conversa de cliente a cada deploy.

### Como decidir sem apostar

O harness de roteiros roda 55 conversas de ponta a ponta trocando uma variável:

```bash
docker compose run --rm -e TETO_USD=0.30 --entrypoint sh shell \
  -c "OPENROUTER_MODELO=google/gemini-2.5-flash-lite python /app/tests/_roteiros_runner.py"
```

Menos de R$ 2 por leva. Compare com o arquivo 24, que tem as mesmas 55 no
Sonnet.

⚠️ **O que olhar não é acurácia**, é se as cinco regras acima sobreviveram. Se
uma cair, R$ 182 por mês não paga.

> ⛔ **O plano grátis do Google não serve para evento real.** No gratuito, o
> conteúdo é usado para melhorar os produtos deles — nome do motorista, placa,
> localização, o áudio transcrito de um pânico. Vincular cobrança sai do
> gratuito na hora (Tier 1, teto de US$ 250/mês) e resolve.

> ⚠️ **Modelo chinês ou aberto muda o problema de lugar.** DeepSeek e Qwen são
> os mais baratos com qualidade defensável, e o dado de cliente passa a sair do
> país para um provedor sem contrato com a Bahrd. Para **teste** é irrelevante;
> para produção, passa por quem responde pela LGPD.

### E se sairmos da OpenRouter para a Anthropic direta?

**Não barateia quase nada.** Conferido na API em 02/09/2026: a OpenRouter cobra
exatamente o mesmo por token que a tabela da Anthropic, inclusive escrita e
leitura de cache. Ela é repasse, não revenda.

O que se economiza são os **5,5% da compra de crédito**: R$ 12/mês no escopo
real, R$ 220/mês nos 43.000.

Migrar continua valendo, mas pelos outros motivos: contrato direto e termos de
dados, uma camada a menos para ficar fora do ar, e o `effort` nativo em vez do
`reasoning` traduzido.

### Por onde comprar

A **OpenRouter não marca preço de token** — repassa a tabela do fornecedor e
cobra **5,5% na compra de crédito**. No volume cheio, ~US$ 83/mês sobre o
Claude. Faz **zero registro de prompt por padrão**.

O que pesa contra ela não é preço: é **um salto de rede a mais**, que custa
latência — e latência decide se a voz soa natural. Some-se mais um ponto de
falha e um contrato que é com a OpenRouter, não com quem roda o modelo.

**Sugestão:** manter a OpenRouter enquanto for comparação de modelo — uma chave
só compara Claude e Gemini por variável — e ir direto no fornecedor escolhido
quando a voz entrar.

---

## A comparação que interessa

Com contenção de **58%**, os 41.000 eventos viram ~23.800 atendimentos que não
chegam a um operador.

| | |
|---|---|
| Custo por atendimento contido | **~US$ 0,04 a 0,11** (R$ 0,24 a R$ 0,62) |
| Custo de um atendimento humano | *a Bahrd tem esse número* |

A conta que decide o projeto é essa divisão, e o segundo número não é nosso —
vale pedir ao gestor antes da próxima reunião.

---

## Confiança de cada linha

| Linha | Origem | Confiança |
|---|---|---|
| Claude | medido, 5 ocorrências reais | **alta** |
| Gemini | catálogo da OpenRouter, lido em 09/09/2026 · perfil de token derivado do Claude | média |
| Gemini 3.8 Flash | preço confirmado · **efeito do cache implícito não medido** | **baixa — confirmar** |
| Deepgram | tabela pública, por minuto | média |
| ElevenLabs | tabela pública, por caractere · cai muito no volume alto | média |
| Inworld (TTS e STT) | tabela pública, lida em 09/09/2026 · **nada medido em áudio nosso** | **baixa — testar** |
| LiveKit | tabela pública, lida em 19/08/2026 | média — **piso, não teto** |
| WhatsApp | tarifa por mensagem, Brasil · só template é cobrado | ✅ **alta — confirmado por fatura em 01/09/2026** |
| Tronco SIP | por minuto, sem cotação ainda | **baixa — confirmar** |
| Número brasileiro | **não está na conta** — sem preço publicado | — |

Câmbio usado: R$ 5,50/US$.

---

## Por onde começar a pagar

Nem tudo precisa ser contratado junto. A ordem abaixo é a do menor
comprometimento primeiro:

| | O quê | Quando |
|---|---|---|
| **1** | **Deepgram** — conta nova, **US$ 0** | agora |
| **2** | **OpenRouter** — US$ 10 a 20 | agora |
| **3** | **ElevenLabs Starter** — US$ 6/mês | **só quando for testar voz** |

**O Deepgram dá US$ 200 de crédito, sem cartão.** A US$ 0,0043/min no Nova-3
pré-gravado — que é o nosso caso, porque baixamos o áudio em vez de usar
streaming —, isso são **775 horas de áudio**, ou ~20.000 atendimentos na
estimativa deste documento. Cobre a POC inteira e boa parte do piloto. Sem
mínimo e sem validade.

**A OpenRouter é pré-paga.** A US$ 0,02/atendimento com o cache ligado, US$ 10
valem ~500 atendimentos. Lembrar dos **5,5%** que eles cobram na compra do
crédito — não há marcação no token, só na recarga.

**O ElevenLabs é o único adiável de verdade.** A IA responde em texto sem ele;
o áudio é opcional no fluxo. O Starter de US$ 6 traz 30.000 créditos — algo
como **50 a 100 atendimentos/mês**, dependendo de o Flash cobrar meio crédito
por caractere. Confortável para afinar voz e entonação, **insuficiente para
piloto com volume** (aí é o Creator, US$ 22).

> ⚠️ **O plano gratuito do ElevenLabs não tem licença comercial.** Para teste
> interno é discutível, mas os US$ 6 tiram a dúvida — é o motivo real para não
> ficar no grátis.

Preços verificados em 19/08/2026.

---

## Quando o WhatsApp cobra, e quando não cobra

A pergunta que aparece toda vez que alguém olha a linha do WhatsApp: *"cada
mensagem da conversa é cobrada?"* Não. **Uma só.**

```
evento dispara
   ↓
IA manda TEMPLATE ......................... R$ 0,034  ← única cobrança
   ↓
cliente responde  →  abre janela de 24 h
   ↓
IA pergunta ............................... R$ 0
cliente responde  →  relógio volta para 24 h
IA pergunta ............................... R$ 0
cliente manda áudio  →  relógio volta para 24 h
IA responde por áudio ..................... R$ 0
   … sem limite de mensagens …
   ↓
IA encerra ................................ R$ 0
```

### Não há limite de rodadas

O limite é de **tempo**, não de quantidade. Vinte mensagens ou cem, o preço é o
mesmo. E o relógio **reinicia a cada mensagem do cliente** — conta a partir da
última vez que *ele* escreveu, não da abertura.

| Situação | Cobra a mais? |
|---|---|
| Ele responde em 2 minutos | não |
| Ele responde em 20 horas | não |
| Ele responde, some, volta 10 h depois | não — a resposta dele reiniciou o relógio |
| Conversa de 3 dias, respondendo todo dia | **não** — cada resposta renova |
| Ele some por 25 h e a IA precisa falar de novo | sim, R$ 0,034 de um novo template |

**Na prática, um atendimento inteiro custa R$ 0,034.** Bateria ou guincho se
resolvem em minutos — nem chegam perto do limite.

### O único caso que renova a cobrança

A IA precisar falar **depois** de mais de 24 h de silêncio do cliente. Nos
playbooks isso quase não acontece:

| Caso | O que acontece |
|---|---|
| Reboque autorizado | desativação de 1 h — o retorno cai dentro da janela · grátis |
| Transporte longo | o lembrete de 1 h também cai dentro · grátis |
| Cliente nunca respondeu | não há janela; o evento fecha sozinho, e evento sem resposta não gera trabalho humano |

### Template dentro da janela aberta também é grátis

Descoberto em 24/08, testando: envio para um celular que estava conversando
passou sem forma de pagamento configurada na conta, e para outro que estava em
silêncio falhou com `131042`.

```
janela ABERTA   →  template UTILITY grátis
janela FECHADA  →  template UTILITY cobrado
```

Isso é uma **rede de segurança de custo**: se a API reiniciar e perder o
rastreio da janela, ela pode disparar um template desnecessário — e a Meta não
cobra por ele. A checagem de `janela_aberta()` na rota `/eventos/link` evita o
envio de qualquer forma; a rede existe para o caso de ela falhar.

> ⚠️ **Vale só para `UTILITY`.** Template `MARKETING` é cobrado sempre, janela
> aberta ou não — mais um motivo para a categoria nunca escorregar. Ver
> 13 · Templates.

### O que isso significa na conta

Dentro do cenário 1, que é o que roda hoje:

| | 8.000 eventos | 41.000 eventos |
|---|---|---|
| WhatsApp · 1 template por evento, **a R$ 0,035 medidos** | ~R$ 280 | ~R$ 1.435 |
| Modelo de linguagem, **medido com cache** | ~R$ 930 | ~R$ 4.760 |
| **Total** | **~R$ 1.210** | **~R$ 6.195** |

**O WhatsApp é ~23% da conta.** O custo continua dominado pelo modelo de
linguagem, e a prioridade não muda: melhorar o cache ou o modelo vale mais que
economizar mensagem. Ver [O que mexe mais na conta](#o-que-mexe-mais-na-conta).

*Esta tabela dizia ~14% e um total de R$ 1.900 / R$ 9.700 até 01/09/2026. A
fatia do WhatsApp subiu não porque ele encareceu, mas porque **o modelo
barateou**: o cache entrou e o preço do Sonnet 5 caiu.*

---

## As três categorias de mensagem

Quem define a categoria é a **Meta**, na aprovação do modelo. É ela que define
o preço.

| Categoria | Para quê | Preço por mensagem |
|---|---|---|
| **`UTILITY`** | evento da conta do próprio cliente — alarme, pedido, entrega | **R$ 0,0340** |
| `MARKETING` | promoção, oferta, campanha | R$ 0,3125 |
| `AUTHENTICATION` | código de verificação em duas etapas | não usamos |

**Os nossos três modelos são `UTILITY`** — é a categoria certa e a mais
barata. `MARKETING` custa **9×** mais: nos 41.000 eventos, R$ 12.813/mês em vez
de R$ 1.394.

> ℹ️ **Mensagem que o cliente inicia não é cobrada.** As três categorias valem
> só para conversa que a empresa começa. Cliente que escreve para a Bahrd abre a
> janela de 24 h, e tudo dentro dela é grátis — ver a seção acima.

### ✅ Confirmado por fatura, 01/09/2026

O cartão entrou e agosto tem cobrança de verdade. Do `pricing_analytics` da
WABA, e a conta é faturada em **`BRL`**:

| Categoria | Mensagens | Custo |
|---|---|---|
| `UTILITY` cobradas | **24** | **R$ 0,84** |
| `UTILITY` grátis, dentro da janela | 158 | R$ 0,00 |
| `SERVICE`, o cliente iniciou | 288 | R$ 0,00 |
| **Total de agosto** | **470** | **R$ 0,84** |

**R$ 0,84 ÷ 24 = R$ 0,035 por template.** O R$ 0,0340 da tabela acima era
estimativa de tabela de terceiro e **agora é medição**, com 3% de diferença.

Duas coisas que a fatura fecha e valem mais que o valor:

* **A moeda.** O 0,034 é em **real**, não em dólar. Se fosse dólar, o WhatsApp
  passaria a custar o dobro do modelo no volume de 41.000, e viraria a maior
  linha da conta. Não é o caso.
* **A categoria.** As 24 saíram como `UTILITY`, não `MARKETING`. O risco de 9×
  descrito acima não se materializou.

E **446 das 470 mensagens saíram de graça**, por estarem dentro da janela de
24 h. O desenho de "um template por ocorrência, conversa livre depois" está
confirmado em produção, não só no papel.


---

## Custo por evento — estimado e medido

### A estimativa, com 4 turnos

| | |
|---|---|
| IA (4 turnos × US$ 0,0089) | R$ 0,196 |
| Template da Meta | R$ 0,034 |
| **Por evento** | **R$ 0,23** |

### O medido, em atendimento real

Ocorrência `OC-2026-08-26-505C-WA`, 26/08/2026, do disparo ao encerramento com
`veiculo_em_manutencao`. Três turnos, **cache quente nos três**:

| Turno | Tokens de cache | Custo |
|---|---|---|
| 1 | 11.409 | US$ 0,0063 |
| 2 | 11.409 | US$ 0,0077 |
| 3 | 11.409 | US$ 0,0071 |
| **Atendimento** | | **US$ 0,0211 · R$ 0,12** |
| Template da Meta | | R$ 0,034 |
| **Por evento** | | **R$ 0,15** |

### Tudo somado, serviço por serviço

As duas tabelas acima contam **só a IA e o template**. Esta conta todo o resto,
e existe porque o número de cima é fácil de confundir com o custo do sistema.

Câmbio de **R$ 5,50**, que é o implícito no resto deste documento.

| Serviço | Por evento | R$ | Quando entra |
|---|---|---|---|
| Claude — **medido** | US$ 0,0211 | R$ 0,12 | sempre |
| Claude — estimado, 4 turnos | US$ 0,0370 | R$ 0,20 | sempre |
| WhatsApp · 1 template | US$ 0,0060 | R$ 0,03 | sempre |
| Langfuse | US$ 0,0041 | R$ 0,02 | sempre |
| Deepgram — ouvir | US$ 0,0100 | R$ 0,06 | cliente manda áudio |
| **ElevenLabs — falar** | **US$ 0,0400** | **R$ 0,22** | IA responde em áudio |

⚠️ **A ElevenLabs sozinha custa quase o dobro da IA inteira.** Ela é a linha que
decide a conta, e é a única de que dá para abrir mão sem perder atendimento.

### A alternativa que ainda não foi testada: Inworld

Levantado em 09/09/2026, a partir das páginas de preço dos dois fornecedores.
**Nada disto foi medido em áudio nosso** — é comparação de tabela.

| Fornecedor · modelo | Por 1M de caracteres |
|---|---|
| ElevenLabs — multilingual padrão (1 crédito/char) | ~$170 |
| ElevenLabs — Flash v2.5 (0,5 crédito/char) | ~$85 |
| **Inworld Realtime TTS-2** | **$25** |
| **Inworld Realtime TTS-2 Flash** | **$15** |

Na base deste documento — US$ 0,04 por atendimento falado, com 3 respostas:

| | Por evento | R$ | 2.250 | 10.000 | 43.000 |
|---|---|---|---|---|---|
| ElevenLabs — hoje | US$ 0,0400 | R$ 0,22 | R$ 495 | R$ 2.200 | R$ 9.460 |
| **Inworld TTS-2** | US$ 0,0118 | **R$ 0,065** | R$ 146 | **R$ 650** | R$ 2.795 |
| Inworld TTS-2 Flash | US$ 0,0071 | R$ 0,039 | R$ 88 | R$ 390 | R$ 1.677 |

**É a maior alavanca de custo do documento.** No cenário com áudio a 10.000
atendimentos, a conta cai de R$ 4.500 para ~R$ 2.950 — **34% do total**,
trocando um fornecedor. Para comparação, a maior economia possível trocando de
modelo de LLM é R$ 182/mês.

Eles também têm STT, a **$0,15/hora** (on-demand) ou $0,10 no Builder — mais
barato que o Deepgram, e com número de confiança, que é o que se perderia
usando um LLM como transcritor.

⛔ **O "mais rápido do mundo" não vale nada para o que existe hoje.** O anúncio
é sub-200ms até o primeiro pedaço de áudio. No WhatsApp a resposta em áudio é
um arquivo: a IA gera, envia, e o motorista abre quando quiser — ninguém está
esperando em tempo real, e 200ms ou 600ms é invisível. A latência vira o motivo
quando a **telefonia** entrar (Sprint 3, `MODO_VOZ` com LiveKit), onde a pessoa
espera em silêncio do outro lado da linha. Hoje, o motivo para olhar o Inworld
é preço, não velocidade.

⚠️ **Duas coisas que a tabela de preço não responde, e decidem:**

1. **Como soa em português do Brasil.** Eles anunciam 200+ idiomas, mas o que
   importa é uma voz que um motorista entenda de primeira, com barulho de
   caminhão em volta.
2. **O catálogo de vozes.** Trocar significa trocar de catálogo. Em compensação
   há clonagem instantânea (5 a 15 s de áudio viram um `voice_id`), então a voz
   atual pode ir junto — e há direção por linguagem natural no meio do texto,
   tipo `[say calmly]`, que num pânico é funcionalmente interessante.

**Como decidir sem gastar:** o plano on-demand inclui **70 minutos de TTS
grátis**. Dá para gerar as frases reais do playbook — a da autorização, a
despedida do pânico, a confirmação de manutenção — e ouvir lado a lado com a
ElevenLabs. É a única coisa que responde a pergunta que importa.

* Playground: `https://platform.inworld.ai/tts-playground`
* Catálogo de vozes: `https://platform.inworld.ai/v2/voice-library`
* Preços: `https://inworld.ai/pricing`

⚠️ **Antes de trocar de fornecedor, olhe a variável.** A maior economia de
áudio não depende de contrato com ninguém: `WHATSAPP_RESPONDER_EM_AUDIO` está
ligada por padrão e dispara sempre que o cliente manda áudio. Responder por
texto em parte desses casos economiza mais que qualquer troca de TTS.

### A média por evento

| | Medido | Estimado |
|---|---|---|
| **Só texto** | **R$ 0,17** | R$ 0,26 |
| **Com áudio** | **R$ 0,45** | R$ 0,53 |

Responder em áudio **triplica** o custo por evento.

### A faixa, para projetar

| Volume | Só texto | Com áudio |
|---|---|---|
| **8.000** — o escopo da POC | **R$ 1.400 – 2.100** | R$ 3.600 – 4.300 |
| 41.000 — todos os eventos | R$ 7.000 – 10.600 | R$ 18.300 – 21.900 |
| 51.000 | R$ 8.800 – 13.200 | R$ 22.800 – 27.200 |

Apresentar com a faixa, não com um número só: a diferença entre as pontas é
quantos turnos a conversa leva para fechar, e isso varia por evento e por
cliente.

⚠️ **O áudio está ligado por padrão** (`whatsapp_responder_em_audio`), e a IA só
usa quando o cliente fala primeiro. Nos testes por texto ele nunca disparou — em
produção, com motorista dirigindo, dispara. Quem for orçar precisa saber em qual
das duas colunas está.

**Ainda fora desta conta:** infraestrutura na OCI, mensalidade do número e
telefonia. Nenhuma delas é grande perto da ElevenLabs; nenhuma delas é zero.

> ⚠️ **O cache é a variável que mais pesa, e não aparece na tabela.** O mesmo
> atendimento de três turnos custou **R$ 0,35** quando o primeiro turno pegou o
> cache frio — quase o triplo. O `ttl` é de 1 hora, então em produção, com ~11
> eventos/hora, ele fica quente sozinho; o buraco é de madrugada. Medir custo
> disparando eventos isolados **infla o número**: dispare em sequência e
> descarte o primeiro.

### Fora desta conta

Infraestrutura na OCI, Deepgram e ElevenLabs (só quando houver áudio), a
mensalidade do número, e o Langfuse — que nestes volumes sai do plano grátis:
um atendimento consome ~18 unidades, então 8.000 dão ~144 mil/mês, contra as 50
mil incluídas. Fica em torno de US$ 33/mês no plano Core.
