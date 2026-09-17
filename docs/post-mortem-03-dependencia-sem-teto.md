# Post-mortem 03 · A dependência sem teto de versão

> **Data:** 17/09/2026 · **Severidade:** baixa · **Estado:** resolvido
> **Duração:** ~15 minutos, do push ao ar de novo
> **Autor:** Leonardo Campos
>
> Ninguém decidiu errado aqui. `pymysql>=1.1` foi escrito assim de propósito,
> para receber correções sem exigir uma edição manual a cada patch. O
> problema não é uma escolha ruim — é uma escolha que confia no futuro do
> pacote de terceiro mais do que deveria.

## Resumo

Um push de documentação, sem nenhuma linha de código tocada, derrubou o
`/saude/pronto` do ambiente de desenvolvimento. A causa não estava no commit:
estava numa dependência que ganhou uma versão nova no PyPI, entre um deploy e
outro, e quebrou uma outra dependência que dependia dela.

## O que aconteceu

O `pyproject.toml` pedia `pymysql>=1.1`, sem teto. O `Dockerfile` instala
direto dele, a cada build — não existe arquivo de lock travando a árvore
inteira. No dia do incidente, o PyPI já tinha publicado o PyMySQL 1.2.1, que
removeu a função `escape_dict` de `pymysql.converters`. O `aiomysql==0.3.2`,
usado para o acesso assíncrono ao MySQL, ainda importa esse nome.

O build de CI pegou o 1.2.1 sem ninguém pedir. A imagem subiu, o processo
iniciou normalmente — o erro só aparecia na hora de abrir conexão com o
MySQL, e o smoke test de *readiness* (`/saude/pronto`) foi quem contou:
`{"mysql": {"ok": false, "erro": "ImportError"}}`.

## Impacto

**Zero em produção.** O pipeline só toca produção depois que o deploy de
desenvolvimento passa nos três smoke tests — e este falhou primeiro, ali. A
esteira parou sozinha, sem ninguém decidir parar.

## Causa raiz

Duas dependências entre si (`aiomysql` → `pymysql`) sem teto de versão numa
delas. `pymysql>=1.1` significa "qualquer versão futura serve", e essa
promessa não é do projeto para cumprir — é do mantenedor de outro pacote, sem
aviso prévio.

## O que funcionou

- O smoke test de *readiness* existe exatamente para separar "o processo
  subiu" de "o sistema funciona" — e foi ele que pegou isto, não uma pessoa
  olhando log.
- O gate `dev` → `prod` fez o trabalho de conter o problema num ambiente só.

## Ação

Travadas as duas versões no `pyproject.toml` (`aiomysql==0.3.2`,
`pymysql==1.2.0`), na combinação que já rodava em produção. Comentário no
próprio arquivo explica o porquê, para a próxima pessoa que for atualizar não
repetir o mesmo salto.

## A lição que sobra

Sem teto de versão não é ausência de decisão — é terceirizar a decisão para
quem nem sabe que este projeto existe. Se o serviço depende do MySQL, ele
depende também da promessa de compatibilidade de quem escreve a biblioteca
que fala com o MySQL — e essa promessa vale o que a versão travada disser.

---

> Relacionado: commit `fix: trava aiomysql e pymysql em versao compativel`.
> Post-mortems mais longos, com mais de um incidente cada: [01](post-mortem-01-pii-no-historico.md) · [02](post-mortem-02-primeiro-deploy.md).
