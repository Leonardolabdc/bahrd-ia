# `infra/terraform/` — infraestrutura da OCI

**Vazio de propósito nesta etapa.** A decisão D7 diz que a POC é construída em
Docker e a OCI é o *destino do deploy*, não pré-requisito. Este diretório existe
desde já porque o plano (doc 02 §3.4) prevê o Terraform **escrito em paralelo**,
para que a infra nasça versionada e não em cliques de console.

## O que entra aqui, e quando

| Sprint | Módulo | Recurso |
|---|---|---|
| 3 | `rede/` | *Compartment*, VCN, subnets, NAT Gateway com IP reservado, Service Gateway |
| 3 | `banco/` | ADB-S 23ai (é o do **deploy de fumaça** que mata a armadilha 1) |
| 4 | `banco/` | MySQL HeatWave DS, OCI Cache |
| 4 | `seguranca/` | Vault + KMS, Dynamic Groups, políticas IAM |
| 4 | `computacao/` | OKE ou VMs Compute, Load Balancer, WAF |
| 4 | `voz/` | VM dedicada do `voice-agent` com IP público e UDP 50000–60000 |
| 4 | `observabilidade/` | Logging, Monitoring, APM |
| — | `orcamento/` | **OCI Budgets com alerta em 50% / 80% / 100%** |

## Regras

1. **Aplicado via OCI Resource Manager**, não `terraform apply` de notebook —
   o *state* fica na conta, não na máquina de alguém.
2. **`orcamento/` é o primeiro a subir.** Obrigatório antes de ligar qualquer
   coisa (doc 02 §3.2).
3. **Nenhum segredo em `.tfvars` versionado.** Valores sensíveis entram como
   variáveis do Resource Manager, e a aplicação os lê do Vault por
   *instance/workload principal*.
4. **Um workspace por ambiente**: `hml` e `prd-poc`.

Região: `sa-saopaulo-1` ou `sa-vinhedo-1`, decidida pela medição de latência
(doc 02 §7.4) — ainda em aberto.
