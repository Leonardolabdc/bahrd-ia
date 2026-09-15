# Post-mortem 02 · O primeiro deploy, e os dez defeitos que ele revelou

> **Data:** 14–15/09/2026 · **Severidade:** alta · **Estado:** resolvido
> **Duração:** ~4 horas, do primeiro `deploy.sh` ao `3/3 passaram`
> **Autor:** Leonardo Campos
>
> Ninguém é nomeado aqui, e não por delicadeza: cinco dos dez defeitos vieram
> do protótipo herdado, e quem os escreveu não está presente para explicar o
> contexto. O que interessa é por que o sistema permitiu que todos
> sobrevivessem até o primeiro deploy.

## Resumo

O primeiro deploy em nuvem falhou **dez vezes seguidas**, por dez causas
diferentes. Nenhuma delas tinha aparecido em 970 testes verdes, em meses de uso
no ambiente local, nem no CI.

Não houve impacto: não havia usuário, nem dado real, nem versão anterior no ar
para derrubar. O custo foi tempo.

## Os dez, na ordem em que apareceram

| # | O que quebrou | A mensagem dizia | A causa era |
|---|---|---|---|
| 1 | Publicação da imagem | `repository name must be lowercase` | o nome do usuário do GitHub tem maiúsculas; o GHCR não aceita |
| 2 | Leitura do wallet | `Permission denied` | arquivo do uid 1000, contêiner roda como 10001 |
| 3 | Conexão com o Oracle | `[Errno 22]` em `create_ssl_context` | o runner não passava `wallet_password` |
| 4 | Criação da auditoria | `ORA-05807 ... greater than 16 days` | pedia 31 dias; o ADB limita a 16 |
| 5 | Migração do MySQL | `Unknown database 'central_ia'` | serviço gerenciado não cria schema sozinho |
| 6 | Redis | `Bad directive` | `--opção=valor` não existe no Redis |
| 7 | Conexão com o MySQL | `'dict' object has no attribute 'wrap_bio'` | o aiomysql atual exige `SSLContext` |
| 8 | Sonda do painel | `Connection refused` | `localhost` → IPv6; o nginx só escuta IPv4 |
| 9 | Painel no navegador | `API inacessível em http://localhost:8000` | `""` é *falsy*, e `\|\|` o tratou como ausência |
| 10 | Painel autenticando | `401` em `/painel/fila` | o token não era escrito no `config.js` |

## Causa raiz

Não é "faltou testar". Os testes existem, são 970, e estavam todos verdes.

**A causa é que o ambiente de desenvolvimento não tem as coisas que quebram.**

O `docker-compose.yml` local sobe Oracle e MySQL em contêiner. Nesse arranjo:

| | Em desenvolvimento | Em produção |
|---|---|---|
| Wallet | não existe | existe, cifrado |
| TLS do MySQL | `DISABLED` | `REQUIRED` |
| Schema | criado pelo compose | precisa ser criado à mão |
| Retenção da auditoria | sem limite | teto de 16 dias |
| Usuário do contêiner | tudo do mesmo dono | uid 10001 lendo arquivo do 1000 |

Cada linha dessa tabela é um **ramo de código que nunca executou**. Os defeitos
3, 4, 5 e 7 vivem exatamente nesses ramos. Eles não passaram despercebidos por
descuido — passaram porque **não havia como o ambiente local encostar neles**.

O projeto já tinha nome para isso. O doc 02 chama de **armadilha 1**:
*"funcionou no Oracle Free, quebrou no Autonomous"*. Estava escrito, previsto, e
aconteceu assim mesmo.

### O agravante

Um dos defeitos tinha um comentário afirmando que ele não existia. O
`persistence/mysql.py` dizia, no cabeçalho:

> *"TLS já é exercitado em local para que `REQUIRED` na Fase 2 não seja a
> primeira vez que o caminho roda."*

A frase descrevia uma intenção. O compose local usa `DISABLED`, então aquele
ramo nunca rodou — e a primeira execução real foi contra o MySQL HeatWave, onde
quebrou na hora.

**Um comentário afirmando que algo é testado não testa nada.** Esse é o achado
que mais vale desta noite.

## O que funcionou

- **Os smoke tests conferem versão, não só disponibilidade.** Num dos deploys a
  API respondia `200` com a versão antiga, porque o passo de migração tinha
  abortado antes de recriar o contêiner. Sem a conferência de versão, aquilo
  teria passado por sucesso.
- **A verificação de integridade das migrações pegou uma alteração real.**
  Ao corrigir um comentário dentro de `001_schema_base.sql`, o runner recusou:
  o sha256 não batia com o que fora aplicado. Estava certo. Migração é
  *append-only* **inclusive nos comentários**, e a nota foi para o runner, onde
  o hash não alcança.
- **Falhar cedo e limpo.** Toda falha parou o deploy em vez de subir pela
  metade. Em nenhum momento o sistema ficou num estado que ninguém escolheu.
- **Publicar por etiqueta de commit.** Um deploy pediu uma imagem que o CD ainda
  não tinha construído e falhou imediatamente, em vez de servir uma versão
  arbitrária — que é o que `latest` teria feito.

## O que não funcionou

- **Confiar que "testado em local" cobre o caminho da nuvem.** Não cobre, por
  construção, quando o local não tem a coisa que a nuvem tem.
- **Mensagens de erro que descrevem o sintoma.** `[Errno 22]` em
  `create_ssl_context` mandou a investigação para permissão de arquivo e depois
  para corrupção de cópia. A causa era uma senha ausente, e nenhuma palavra do
  erro sugeria isso. Duas investigações erradas antes da certa.

## Ações

| # | Ação | Estado |
|---|---|---|
| 1 | `parametros_wallet` como única fonte de verdade para conexão Oracle | ✅ feito |
| 2 | `test_mysql_tls.py` — o ramo TLS passa a ser exercitado de verdade | ✅ feito |
| 3 | Teto de 16 dias registrado onde o hash da migração não alcança | ✅ feito |
| 4 | Sonda do painel em `127.0.0.1`, e no endpoint dedicado | ✅ feito |
| 5 | `??` em vez de `\|\|` onde string vazia é valor legítimo | ✅ feito |
| 6 | Token do painel injetado na borda, nunca entregue ao navegador | ✅ feito |
| 7 | Um perfil de compose que aponte o ambiente local para os bancos gerenciados | 📋 aberta |
| 8 | Deploy de fumaça contra o ADB **antes** do deploy completo, como o doc 05 já recomendava | 📋 aberta |

As ações 7 e 8 atacam a causa raiz; as seis primeiras atacam os sintomas. É
honesto dizer que só elas duas impedem a próxima repetição.

## A lição que sobra

**Paridade de ambiente não é ter os mesmos serviços — é exercitar os mesmos
caminhos de código.** Ter Oracle em contêiner e Oracle gerenciado não é
paridade se um usa wallet e o outro não, porque o código que lida com wallet
continua sem nunca rodar.

O jeito barato de descobrir isso é o que o doc 05 já mandava fazer e que não foi
feito: **provisionar só o banco, cedo, e rodar tudo contra ele**. Os dez defeitos
teriam aparecido em uma tarde tranquila, e não em quatro horas na véspera.

---

> Relacionado: [auditoria do protótipo](auditoria-prototipo.md) ·
> [ADR-002](adr/0002-plataforma-de-publicacao.md) ·
> [post-mortem 01](post-mortem-01-pii-no-historico.md)
