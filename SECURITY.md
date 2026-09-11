# Segurança

## Como relatar

Achou uma falha? **Não abra issue.** Fale direto com o responsável técnico do
projeto ou com a TI da Bahrd Monitoramento.

Issue pública num repositório de empresa é aviso ao atacante antes de ser aviso
a quem conserta.

## O que este sistema é, para calibrar o risco

Uma IA conversa por WhatsApp com motoristas e gestores de frota sobre alarmes
de veículo. Ela recebe eventos de rastreamento e responde no número oficial da
Bahrd.

Duas consequências disso valem mais do que parecem:

**O número que envia é verificado.** Uma mensagem com link saindo daqui seria
phishing com a credibilidade da empresa — o cliente confia porque veio do
número certo. É por isso que a IA não pode mandar link nenhum, sem exceção.

**Quem escreve do outro lado não é auditado.** Todo texto que chega é entrada
não confiável, inclusive o que vem no cadastro do cliente pelo webhook.

## A decisão de arquitetura que mais protege

⭐ **A IA não tem ferramenta nenhuma.** Ela recebe texto e devolve texto. Não
consulta banco, não abre arquivo, não chama API, não executa nada.

Isso não é limitação a ser removida quando der: é a proteção principal. Uma
injeção de prompt bem-sucedida em qualquer ponto faz a IA **escrever bobagem
para quem a provocou** — não faz a IA agir.

Existem testes cuja única função é quebrar se alguém der ferramenta a ela. Não
para impedir, mas para garantir que seja decisão consciente e revisada, e não
um detalhe que passa numa sexta-feira.

Quando a escrita no sistema da Bahrd existir, ela entra por
`orchestration/tratativas.py`, e por lá as operações são um conjunto **fechado**
de ações nomeadas — nunca comando livre, nunca parâmetro que vira SQL. As
regras estão no doc 17.

## Camadas que existem hoje

| Camada | Onde | Contra o quê |
|---|---|---|
| Assinatura HMAC dos eventos | `api/rotas/eventos.py` | evento forjado |
| Assinatura da Meta | `integrations/mensageria/meta.py` | webhook forjado |
| Teto e detecção de injeção na entrada | `agent/blindagem.py` | virar as instruções |
| Bloqueio de link, tamanho e vazamento na saída | `agent/blindagem.py` | phishing pelo nosso número |
| Remoção de HTML | `agent/escrita.py` | script na tela do operador |
| Higiene do payload | `integrations/rastreamento/bahrd_webhook.py` | injeção pelo cadastro |
| Lista branca de desfechos | `domain/eventos.py` | fechar caso com motivo inventado |
| Teto de turnos, tempo e tokens | `orchestration/sessao_whatsapp.py` | esgotar orçamento |

Detalhe de cada uma em [`docs/07-seguranca.md`](docs/07-seguranca.md), que
**está** neste repositório.

⚠️ Isto aqui já dizia que `docs/` não estava no repositório, e essa frase estava
errada. O desenho real do `.gitignore` é mais cuidadoso do que ela sugeria:
`docs/*` ignora a pasta inteira, e **22 exceções nomeadas uma a uma** trazem de
volta só os documentos referenciados no README, para que os links não deem 404.

O padrão é não publicar. Publicar é decisão consciente, uma linha por vez.

As três subpastas com material sensível (`docs/arquivo/` com documentos
superados, `docs/interno/` com prints de conversa de gestor, `docs/exemplos/`
com relatório de evento contendo dado real de cliente) **nunca são
excepcionadas**, e `test_o_gitignore_cobre_o_que_nao_pode_subir` quebra se
alguém tentar. Uma varredura dos 22 publicados em 01/09/2026 não achou
credencial, telefone real nem placa real.

## A superfície exposta

Enquanto o túnel estiver ligado, a API é alcançável da internet. O túnel expõe
hoje a **raiz**, ou seja, todas as rotas, e nem todas precisam disso:

| Rota | Tranca | Precisa ser pública? |
|---|---|---|
| `/whatsapp/meta` | assinatura HMAC da Meta | sim, a Meta entrega aqui |
| `/eventos` | HMAC da Bahrd | sim, a Bahrd entrega aqui |
| `/midia/*` | nenhuma, por desenho | sim, enquanto o áudio for entregue por URL |
| `/painel/*` | `PAINEL_TOKEN` | **não**, o painel é aberto localmente |
| `/painel/testes/*` | `PAINEL_TOKEN` + lista fechada de destino + teto diário + 404 fora de dev | **não**, é ferramenta interna |
| `/saude/*` | nenhuma, por desenho | **não**, o `HEALTHCHECK` roda dentro do contêiner |

### A tela de eventos de teste

Ela existe porque quem valida o atendimento é a Central, e validar não pode
depender de o dev montar JSON no Postman. É a **única parte do sistema em que o
telefone de destino é escolhido por uma pessoa**, e não por um evento de
veículo, e é por isso que é a mais travada:

* o destino sai de `PAINEL_NUMEROS_DE_TESTE`, uma lista fechada e separada da
  do Twilio, revalidada no servidor; vazia recusa tudo;
* o corpo do evento é montado pelo servidor a partir de um catálogo de três,
  nunca recebido pronto. A alternativa, assinar o que o chamador mandasse, seria
  um oráculo de assinatura: o HMAC deixaria de significar "veio da Bahrd";
* o teto é rígido, 50 por dia, e some à meia-noite;
* a rota devolve **404** fora de desenvolvimento, e não 403, porque 403
  confirmaria que ela existe num `/openapi.json` que hoje está público;
* o modelo é enum fechado de dois valores. String livre daria acesso ao catálogo
  inteiro da OpenRouter, inclusive modelos de US$ 75 por milhão de tokens.

⚠️ **Aqui o princípio "alerta de custo, nunca teto" do resto deste documento não
vale, e a inversão é deliberada.** Teto no caminho de atendimento vira cliente
real sem resposta; teste bloqueado não custa a ninguém.

O risco que este desenho combate não é o atacante, é o **erro de digitação**: um
dígito trocado mandaria "Acionamento do botão de pânico", com botão de ligação
para o 0800 real, para a casa de um estranho.

As duas últimas linhas são ganho de graça: tirar essas rotas do túnel não
quebra nada e reduz a superfície. `/saude/pronto` é a única rota do sistema em
que uma requisição barata provoca trabalho caro, três consultas de banco por
chamada, e é a que menos motivo tem para estar exposta.

⚠️ **O endereço do túnel não é segredo.** Ele precisa de certificado TLS, e
nome com certificado emitido aparece nos registros públicos de Certificate
Transparency, que são varridos por scanner o tempo todo. Quem protege é a
tabela acima, não o desconhecimento do endereço.

## Mapa OWASP Top 10 para LLM

Feito em 01/09/2026, para o projeto poder ser conferido contra um catálogo que
existe fora dele:

| Item | Onde está tratado | Situação |
|---|---|---|
| **LLM01** injeção de prompt | `agent/blindagem.py`, `policy_guardrails.md`, e a higiene de fronteira em `bahrd_webhook.py` para a injeção indireta | coberto |
| **LLM05** saída insegura | `sem_html()` em `agent/escrita.py`, mais o bloqueio de link em `blindagem.py` | coberto |
| **LLM06** agência excessiva | a IA não tem ferramenta nenhuma, e dois testes quebram se alguém der uma | coberto por arquitetura |
| **LLM07** vazamento do prompt | `vazou_o_prompt()`, comparando contra os blocos reais da chamada | coberto |
| **LLM08** fraquezas no RAG | não se aplica, não existe RAG nem banco vetorial | fora de escopo |
| **LLM10** consumo excessivo | tetos de entrada, de saída, de turnos e de sessão | **parcial**, ver abaixo |

A cadeia de ataque que o catálogo descreve está quebrada no elo do meio, e é de
propósito: sem LLM06 não existe injeção que termine em ação, só em texto.

## O que ainda não existe

Escrito para ninguém descobrir sozinho e tarde:

- **Rate limiting.** Nenhum, em nenhuma camada, exceto o teto diário de
  `/painel/testes/evento`. O custo de uma conversa já é fechado pelos 5 turnos,
  então o risco não é a conta do modelo: é chute ilimitado no `PAINEL_TOKEN` e
  martelada em `/saude/pronto`. ⚠️ Quando houver, o balde tem de ser por token e
  por número de destino, **nunca por IP**: atrás do túnel todo pedido chega do
  mesmo endereço, e limitar por IP limitaria todo mundo junto.
- **Alerta de custo.** O gasto real de cada chamada é registrado, mas ninguém é
  avisado quando ele sobe. O `TETO_USD` existe só no runner de roteiros.
- **Login por operador.** O painel usa um segredo compartilhado, não conta de
  usuário. É limite conhecido, o roteiro está no doc 07.
- **Pseudonimização.** Nome e placa vão inteiros para o modelo.

O plano de fechar isso sem derrubar atendimento está em `docs/arquivo/`, fora
deste repositório.

## O que não pode entrar no repositório

Três coisas, e as três têm guarda automático em
`tests/test_nada_de_dado_real_no_repositorio.py`:

- **Credencial de fornecedor.** O `.env` é ignorado pelo Git e nunca esteve no
  histórico. O `.env.example` documenta as chaves e **jamais** os valores.
- **Telefone de gente de verdade.** Use número de dígitos repetidos
  (`+5541999999999`), que qualquer leitor reconhece como inventado.
- **`docs/` por padrão.** A regra é `docs/*`, e cada documento que sobe entra
  por exceção nomeada. Documento novo só aparece no Git se alguém escrever a
  linha, o que torna publicar uma decisão e não um descuido.

Ative a trava logo após clonar. É o único passo que não dá para recuperar
depois: segredo commitado não sai com `git revert`.

```bash
git config core.hooksPath .githooks     # só Git, nada a instalar
```

Quem tiver Python pode usar o `.pre-commit-config.yaml` no lugar, que roda o
`gitleaks` completo e os testes de guarda: `pip install pre-commit &&
pre-commit install`.

## Antes do primeiro evento real

Quatro itens de configuração, e nenhum é código. O estado conferido em
01/09/2026 está ao lado de cada um:

- `BAHRD_WEBHOOK_HMAC_SECRET` precisa do segredo real combinado com a TI. O
  valor de desenvolvimento se chama `dev-hmac-nao-usar-em-producao` justamente
  para não passar despercebido, e está versionado no `.env.example` desde
  `d62f5b1`: quem lê o repositório consegue assinar um POST válido.
  ⚠️ **Até 03/09/2026 isso era pior do que parecia.** A lista de destinos
  autorizados de `/eventos/link` só valia quando não havia segredo configurado,
  pelo raciocínio de que a assinatura já provava quem chamava. Com o
  placeholder no lugar, a conta fechava ao contrário: qualquer pessoa com
  leitura do repositório assinava um POST e fazia o número oficial verificado
  da Bahrd mandar template, inclusive o de pânico, para qualquer celular do
  Brasil. Preencher o segredo, que é a coisa certa a fazer, era o que desligava
  a proteção. Hoje quem decide essa trava é `APP_ENV`: fora de produção a lista
  vale sempre, com assinatura ou sem, e lista vazia recusa tudo.
- `LANGFUSE_ENVIAR_CONTEUDO=false`. Em `true`, nome, placa e endereço do cliente
  vão para a nuvem do Langfuse. A aplicação já ignora essa variável quando
  `APP_ENV` é de produção, mas a configuração deve refletir a intenção.
- `PANICO_AUTONOMO`. Em `true`, a IA pode encerrar sozinha um pânico que ela
  classificou como alarme falso. É a única exposição conhecida do sistema, está
  ligada de propósito para medir a qualidade da triagem, e a decisão de
  desligar é de operação.
- **O túnel expõe a raiz.** Estreitar para os três caminhos que a Meta, a Bahrd
  e a busca de áudio usam tira `/painel/*` e `/saude/*` da internet sem quebrar
  nada. É configuração do túnel, não da aplicação.

Estado em 01/09/2026, num ambiente ainda de desenvolvimento (`APP_ENV=dev`):

| Item | Como está |
|---|---|
| `BAHRD_WEBHOOK_HMAC_SECRET` | ⚠️ ainda o placeholder `dev-hmac-nao-usar-em-producao`, versionado e público no repositório |
| Destinos de `/eventos/link` | ✅ desde 03/09/2026 a lista vale sempre fora de produção; antes o placeholder acima a desligava |
| `LANGFUSE_ENVIAR_CONTEUDO` | ⚠️ `true`, e com `APP_ENV=dev` o conteúdo sai mesmo |
| `PANICO_AUTONOMO` | `true`, decisão consciente |
| Túnel | ⚠️ expondo `/` |
| `PAINEL_TOKEN` | ✅ definido |
| `META_APP_SECRET` | ✅ definido |

Nenhum desses ⚠️ é erro enquanto o ambiente é de teste e os únicos números
autorizados são os de dentro de casa. Todos viram erro no dia em que um cliente
de verdade entrar.

⚠️ Essa frase era falsa até 03/09/2026, e vale registrar por quê: ela assume
que existe uma lista de números de dentro de casa valendo, e o placeholder de
HMAC desligava exatamente essa lista. A premissa da conclusão estava quebrada
pela linha de cima da mesma tabela. Hoje a lista vale de novo, e a frase volta
a se sustentar. Fica aqui porque suposição escrita e não conferida é o tipo de
erro que este documento existe para não repetir.
