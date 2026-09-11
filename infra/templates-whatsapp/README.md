# Modelos de mensagem do WhatsApp

Os **três** modelos que o código usa, como *payload de envio* — a fonte da
verdade do texto que o cliente da Bahrd recebe.

Explicação do desenho e histórico das versões em
[`a documentação interna do projeto`](../../a documentação interna do projeto).

## Os arquivos

| Arquivo | Modelo | Quando é usado |
|---|---|---|
| `alerta-saudacao-mapa.json` | `evento_alerta_saudacao_mapa` | bateria e movimento, com coordenada |
| `alerta-saudacao.json` | `evento_alerta_saudacao` | os mesmos, sem coordenada |
| `panico-saudacao-mapa.json` | `evento_panico_saudacao_mapa` | pânico, com coordenada |
| `panico-saudacao.json` | `evento_panico_saudacao` | pânico, sem coordenada |
| `alerta-mapa.json` · `alerta-texto.json` | `evento_alerta_mapa` · `evento_alerta` | **reserva** do alerta |
| `panico-mapa.json` · `panico-texto.json` | `evento_panico_mapa` · `evento_panico` | **reserva** do pânico |

Bateria e movimento dividem um modelo só porque o tipo do evento entra como
parâmetro — qualquer um do catálogo cabe ali sem modelo novo. O pânico tem o
seu porque o `PB-PANICO` proíbe nomear o evento, e o genérico o nomeia.

## As duas gerações, e por que a antiga fica

A geração `_saudacao` abre chamando a pessoa pelo nome, com "bom dia", "boa
tarde" ou "boa noite" pela hora do evento. A anterior não cumprimenta.

> ⛔ **A reserva não é sobra, é a rede.** Um modelo novo passa horas em análise
> na Meta e pode ser reprovado ou pausado depois. A rota tenta a geração nova
> primeiro; enquanto ela não vale, a antiga entrega a mensagem. É isso que faz
> um modelo entrar em produção sozinho, sem deploy e sem nenhum minuto sem
> notificação — ver `templates_do_evento`.

> ⚠️ **Esta lista é a cota de edição.** O `enviar.ps1` edita todos os modelos do
> `modelos.json`, e cada um só aceita uma edição a cada 24 h. Modelo órfão na
> lista queima a cota do dia sem motivo — por isso saíram daqui, em 10/09/2026,
> os quatro de bateria e movimento por tipo e as quatro variantes `_nome`, que
> a saudação tornou desnecessárias. **Todos continuam aprovados na Meta**;
> apagar de lá é decisão à parte e não é necessária.
>
> Use `-Somente` para mexer em um sem tocar nos outros.

## Enviar

```powershell
.\infra\templates-whatsapp\enviar.ps1
```

Lê o token do `.env`. **Não gera cobrança** — criar e editar modelo é grátis.

> ⚠️ **Uma edição por modelo a cada 24 h.** É por isso que este script manda
> tudo de uma vez: gastar a cota do dia numa correção de cada vez custa 24 h de
> espera pela próxima. Ajuste todos os arquivos, depois rode uma vez só.
>
> **Última edição dos três: 10/09/2026.** A trava abre no mesmo horário do dia
> seguinte. Rodar antes faz os três voltarem com erro e gasta a tentativa.

Acompanhar o resultado da análise:

```powershell
GET /931502646668768/message_templates?fields=name,status,category
```

## O que a Meta recusa, aprendido na marra

Cada uma destas custou uma tentativa — e, com a trava de 24 h, um dia.

* **Botão não aceita emoji.** Nem variável, nem quebra de linha, nem
  formatação. No botão, o que é nosso são as palavras e mais nada.
* **Variável não pode ser a última coisa do corpo.** Por isso os modelos de
  alerta terminam convidando a escolher uma opção, e não em `Local: {{4}}`.
* **`address` é obrigatório** no bloco de localização. Sem ele o modelo com
  mapa falha e o motorista não recebe nem o aviso do alarme.

E uma que não é regra da Meta, mas custa igual: **a ordem dos parâmetros é
contrato**. Trocar `{{1}}` com `{{2}}` manda o evento no lugar da placa, e a
Meta aceita numa boa — ela não sabe o que cada um significa. Quem garante a
ordem é o `parametros` do `modelos.json`, e ela precisa bater com a sequência
que o `eventos.py` monta.

## Formatação no corpo

O WhatsApp aceita `*negrito*`, `_itálico_` e `~riscado~` no texto. **Não existe
cor de fonte** — nem em modelo, nem em mensagem comum.

Os modelos de alerta usam negrito em dois lugares só: a placa e o tipo do
evento. Negrito funciona por contraste; em tudo, vira ruído. São os dois dados
que o motorista precisa pegar de relance — qual caminhão, e o que aconteceu.
