# Post-mortem 01 · Dado pessoal no histórico do Git

> **Data do incidente:** 11–12/09/2026 · **Severidade:** alta · **Estado:** resolvido
> **Autor:** Leonardo Campos
>
> Este documento não nomeia responsáveis, e isso é deliberado. O protótipo foi
> herdado; quem escreveu as linhas não está aqui para se defender, e um
> post-mortem que procura culpado ensina o time seguinte a esconder defeito em
> vez de relatá-lo. O que interessa é por que o sistema permitiu.

## Resumo

Ao preparar a publicação do repositório, uma varredura encontrou **dado pessoal
de cliente real** — um telefone e um endereço residencial completo — presentes
no histórico do Git **desde o commit inicial**. O repositório ainda era privado,
e nenhum dado chegou a ficar público.

Um segundo levantamento, feito depois porque a primeira correção parecia boa
demais, encontrou **mais quatro classes** de identificador de terceiro que a
primeira passada não viu.

## Linha do tempo

| Quando | O quê |
|---|---|
| Commit inicial | Telefone e endereço reais entram, dentro de uma ocorrência de exemplo |
| Meses depois | Um commit os remove **de um documento** — e a checagem dá por encerrado |
| 11/09, manhã | Varredura de `git log -S` antes de publicar acha o telefone em **8 commits** |
| 11/09, tarde | Decisão: histórico novo, e não reescrita do antigo |
| 12/09 | Pergunta "tem certeza?" motiva uma segunda passada |
| 12/09 | A segunda passada acha ID de conta WhatsApp Business, 8 IDs de modelo, 6 IMEIs de rastreador, e **o mesmo endereço sobrevivendo num arquivo de teste** |
| 12/09 | Repositório recriado com histórico de um commit só, já sanitizado |

## Impacto

**Nenhum, e por pouco.** O repositório nunca esteve público. O que existiu foi
exposição latente: qualquer clone, backup ou push acidental teria distribuído o
dado, e nenhuma dessas ações teria disparado alerta.

## Causa raiz

A causa não é "alguém colocou dado real no código". Isso é o sintoma.

**A causa é que dado real e dado de exemplo tinham a mesma aparência no
repositório, e nada no caminho os distinguia.** Uma ocorrência de amostra com
telefone de verdade é indistinguível de uma com telefone inventado — para o
revisor, para o `grep`, e para o `gitleaks`, que procura *credencial*, não
*pessoa*.

Três coisas se somaram:

1. **Não havia trava automática.** O `gitleaks` roda desde sempre, mas o padrão
   dele é chave de API. Telefone e endereço brasileiros não são segredo no
   sentido que ele entende, e passaram.
2. **A primeira correção olhou o lugar errado.** Removeu o dado do documento em
   que alguém o tinha visto, e não *do repositório*. A diferença entre
   `grep` num arquivo e `git log -S` em toda a história é a diferença entre
   achar uma ocorrência e achar todas.
3. **Código de amostra não é revisado como código de produção.** Os IMEIs
   estavam num arquivo de exemplo. O próprio `.gitignore` do projeto já
   classificava IMEI como dado que não se versiona — e ele estava versionado
   assim mesmo, porque ninguém lê `exemplos/` com o mesmo cuidado.

## O que funcionou

- **A varredura aconteceu antes de publicar.** A ordem das etapas foi o que
  transformou um vazamento num quase-vazamento.
- **A desconfiança da primeira correção.** A segunda passada só existiu porque
  alguém perguntou "tem certeza?" em vez de aceitar o primeiro resultado — e
  ela achou quatro classes de dado que a primeira não viu.
- **Histórico novo em vez de `filter-repo`.** Reescrever deixa rastro em
  *packfile* e não alcança clone já feito. Recomeçar custou um commit e
  resolveu de fato.

## O que não funcionou

- **Confiar que remover de um arquivo remove do repositório.** Não remove. O
  Git guarda tudo, e foi exatamente esse mal-entendido que deixou o dado vivo
  por meses depois de "corrigido".
- **Tratar `gitleaks` como cobertura completa.** Ele cobre credencial. Dado
  pessoal é outra categoria e precisa de outra regra.

## Ações

| # | Ação | Estado |
|---|---|---|
| 1 | Histórico novo, sanitizado, com um commit de origem | ✅ feito |
| 2 | `gitleaks` no CI com `fetch-depth: 0` — varre a história, não o checkout | ✅ feito |
| 3 | Mesmo `gitleaks` em hook de pre-commit, onde ele evita o dano em vez de relatá-lo | ✅ feito |
| 4 | Regras próprias no `.gitleaks.toml` para telefone e CEP brasileiros | 🔄 em andamento |
| 5 | Todo dado de amostra passa a ser gerado, nunca copiado de ocorrência real | ✅ feito |
| 6 | Revisar `exemplos/` e `tests/` com o mesmo rigor de `src/` | 📋 aberta |

## A lição que sobra

**A pergunta certa não é "removi o dado?", é "o dado ainda existe em algum
lugar da história?".** São perguntas diferentes, e só a segunda tem uma resposta
que se pode verificar com um comando.

---

> Relacionado: [auditoria do protótipo](auditoria-prototipo.md), lacunas 1 e 2.
