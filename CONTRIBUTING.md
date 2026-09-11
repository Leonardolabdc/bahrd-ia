# Como mexer neste projeto

O README explica **o que** o sistema faz. Este arquivo é sobre as convenções
que não se descobrem lendo o código, e sobre as poucas regras que existem
porque já custaram caro uma vez.

## Primeiro clone

```bash
make setup      # cria o .env a partir do .env.example
make up         # sobe api, worker, web, oracle, mysql, redis, minio
make test       # 747 testes, sem tocar rede nem API paga
```

E o passo que não dá para recuperar depois:

```bash
git config core.hooksPath .githooks
```

Uma linha, sem instalar nada. A partir daí, todo commit passa por
`.githooks/pre-commit`, que barra `.env`, chave de API, telefone de gente real
e arquivo grande demais.

Sem isso, nada impede um `.env` de entrar no commit. E segredo commitado não
sai com `git revert` — sai reescrevendo o histórico inteiro. Ver `SECURITY.md`.

### Se você tem Python na máquina

Há também um `.pre-commit-config.yaml`, que roda mais coisa: `gitleaks`
completo, `ruff` e os testes de guarda.

```bash
pip install pre-commit && pre-commit install
```

Os dois cobrem o essencial e **não precisam conviver** — escolha um. O do Git
existe porque nem toda máquina do time tem Python, e proteção que só funciona
em algumas máquinas protege em algumas máquinas.

## As regras que existem por um motivo

### A IA não tem ferramenta, e isso é proposital

Ela recebe texto e devolve texto. Se um prompt mandar chamar uma função, o
modelo **não vai chamar** — ele vai *inventar que chamou*, e prometer ao cliente
uma consulta que nunca acontece.

Isso aconteceu duas vezes em 27/08/2026, com `validar_credencial` e
`consultar_posicao_veiculo`. Nos dois casos a IA disse ao cliente que ia
verificar, e a conversa travou. Há teste varrendo os prompts atrás de nome de
função que não exista no código.

### Prompt não usa travessão

O modelo copia o estilo do que lê. Um travessão no prompt vira travessão na
mensagem do WhatsApp, e ninguém escreve assim num celular. Há teste.

### Frase que o cliente precisa entender vai prescrita

Quando a clareza importa mais do que soar espontâneo, escreva a frase no prompt
e proíba sinônimo. A IA já explicou o fim de uma proteção com *"assim que ele
saltar daí"*, que não é português de ninguém.

O oposto também vale: **nunca deixe jargão interno vazar para a conversa**. O
cliente não sabe o que é "regra de base".

### Telefone em código é sempre inventado

Use dígitos repetidos: `+5541999999999`. O guarda automático rejeita qualquer
número com 5 ou mais dígitos distintos na parte do assinante, porque é assim
que se parece o número de uma pessoa de verdade.

### Exceção de segredo vai no `.gitleaks.toml`, pelo valor

A varredura roda no CI sobre o **histórico inteiro**, não sobre o checkout: um
segredo removido no último commit continua nos anteriores.

Quando ela apontar algo que é placeholder de verdade, a exceção vai no
`.gitleaks.toml` **com o motivo escrito**, e liberando o **valor**, nunca o
caminho do arquivo. A diferença importa: liberar `.env.example` inteiro deixaria
passar uma senha real colada ali amanhã; liberar o valor não.

Existe exatamente uma exceção hoje, a senha do Oracle local, e ela tem seis
linhas de justificativa ao lado.

O CI usa a **imagem oficial do gitleaks com versão fixa**, e não a action do
marketplace: ela cobra licença quando o repositório pertence a uma organização.

### De `docs/`, sobe o que o README referencia

Os documentos numerados sobem, porque sem eles os links do README dariam 404.
Três subpastas não sobem, e a razão é o conteúdo:

| | |
|---|---|
| `arquivo/` | documentos superados — guardados porque contam **por que** decisões foram tomadas |
| `interno/` | prints de conversas dos gestores |
| `exemplos/` | planilha com dado real de cliente |

A regra no `.gitignore` é `docs/*` mais uma lista explícita de exceções.
**Documento novo não sobe sozinho** — precisa ser acrescentado à lista, e isso é
de propósito: o padrão é não publicar. Há teste conferindo as duas metades.

⚠️ Note o asterisco. Com `docs/` o Git não entra na pasta para avaliar exceção,
e todos os `!docs/...` seriam descartados junto.

## Testes

A suíte roda sem banco, sem rede e sem API paga — todo teste que precisaria de
uma delas usa dublê. Se um teste seu precisa de rede, o desenho está errado.

Escreva o teste explicando **por que ele existe**, não o que ele faz. O que ele
faz está no código; por que ele existe é o que salva quem for mexer nisso daqui
a seis meses. Vários testes deste repositório documentam um defeito real, com
data e sintoma — esse é o padrão.

### E existe um segundo tipo de teste, que não é da suíte

A suíte responde *"o código faz o que a gente escreveu"*. Ela não responde
**o que a IA de fato diz para uma pessoa**, e é aí que os defeitos caros moram.

Para isso existe o `tests/_roteiros_runner.py`, com 55 roteiros escritos como um
motorista escreve: erro de digitação, caixa alta, gíria, mensagem picada,
cliente irritado, tentativa de injeção de prompt. Ele roda o caminho de produção
inteiro, do payload da Bahrd ao desfecho e à tratativa, com o cliente da Meta
trocado por um dublê. Nenhuma mensagem sai, nenhum template é disparado.

```bash
docker compose run --rm -e TETO_USD=0.90 --entrypoint sh shell \
  -c "python /app/tests/_roteiros_runner.py"
```

O `_` no nome mantém o pytest longe: ele produz conversas para alguém ler, não
asserções. **Ele chama o modelo de verdade, então custa dinheiro**: cerca de
US$ 0,017 por conversa, menos de US$ 1 a leva inteira. O `TETO_USD` faz a
rodada parar sozinha.

Rode depois de mexer em prompt. Em 28/08/2026 a primeira leva achou catorze
defeitos que a suíte inteira não pegava, entre eles um turno que estourava o
orçamento de tokens e derrubava a conversa.

## Commits

Mensagem em português, no imperativo, dizendo **o que mudou e por quê**:

```
fix: a IA para de prometer consultas que nao tem como fazer

Alucinacao real, 27/08/2026, nos DOIS numeros ao mesmo tempo. O cliente
disse "foi o pessoal da oficina" e a IA respondeu "So um segundo, vou
confirmar aqui a localizacao" — e ficou esperando por si mesma.
```

O corpo conta o sintoma, a causa e a razão da escolha. Quem lê `git log` daqui
a um ano precisa entender a decisão sem abrir o código.

## Modelos de mensagem do WhatsApp

Vivem em `infra/templates-whatsapp/`, e a aplicação os lê em tempo de execução
para saber o texto que o cliente já recebeu — mexer neles muda o que a IA
considera "já dito" na primeira resposta.

O canal padrão do projeto é o sandbox do Twilio, que não exige modelo aprovado.
Os arquivos seguem no formato da Meta para que trocar de canal continue sendo
configuração, e não reescrita.

As regras de composição — botão não aceita emoji, variável não pode abrir nem
fechar o corpo, o rodapé renderiza entre o corpo e os botões — estão na tabela
do [README da pasta](infra/templates-whatsapp/README.md).

## Onde o código mora

O repositório é **público**, em
[`Leonardolabdc/bahrd-ia`](https://github.com/Leonardolabdc/bahrd-ia).

Toda mudança nasce em branch e entra por Pull Request. A `main` reflete o que
está em produção; a `dev`, o que está em validação.

```bash
git checkout -b nome-da-mudanca
git push -u origin nome-da-mudanca
```

O GitHub responde com o link para abrir o PR, e o CI roda na branch — lint,
testes, varredura de segredo e build do front. **Merge só com o CI verde**, que
é o mecanismo, não a convenção: sem ele, "não quebrar a main" seria só um
acordo verbal.
