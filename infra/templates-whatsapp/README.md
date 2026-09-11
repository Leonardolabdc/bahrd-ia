# `infra/templates-whatsapp/`

Os textos que abrem o atendimento, no formato que a API do WhatsApp aceita.

**Eles não existem só para publicar na Meta.** A aplicação os lê em tempo de
execução, em `integrations/mensageria/modelos.py`, para saber *o que o cliente
já leu* — sem isso a IA repetiria na primeira resposta tudo o que a notificação
já tinha dito, e a conversa começaria com o cliente lendo a mesma coisa duas
vezes.

## Como se liga

`modelos.json` é o manifesto: mapeia o nome do modelo para o arquivo. Quem
acrescenta um modelo cria o `.json` e registra ali — a aplicação e os testes
leem os dois.

Cada arquivo traz os componentes na forma da API: `BODY` com as variáveis
numeradas, `FOOTER` quando existe, e `BUTTONS` com as respostas rápidas.

## As regras de composição que custaram para descobrir

| Regra | Consequência de ignorar |
|---|---|
| O corpo não pode **começar** com variável | modelo recusado na aprovação |
| O corpo não pode **terminar** com variável | modelo recusado |
| Botão não aceita emoji | modelo recusado |
| Variáveis numeradas em ordem crescente no texto | modelo recusado |
| `FOOTER`: 60 caracteres, sem variável, sem negrito | modelo recusado |
| O `FOOTER` renderiza **entre** o corpo e os botões | a última linha do corpo não pode dizer "escolha abaixo" |
| Bloco de localização exige `address` | cartão de mapa não renderiza |

A última é a menos óbvia e a que mais confunde: a posição do rodapé é fixa e
não dá para mudar. Uma frase que aponte "as opções abaixo" acaba apontando para
o rodapé, e por um instante ele parece ser uma das opções. Por isso o corpo
fecha com uma pergunta, que não aponta para lugar nenhum.

## Neste projeto

O canal padrão é o **sandbox do Twilio** (`CANAL_WHATSAPP=twilio`), que não
exige modelo aprovado: dentro da janela de 24 h a mensagem vai livre. Estes
arquivos continuam sendo a fonte do texto de abertura, e seguem no formato da
Meta para que trocar de canal seja configuração, e não reescrita.
