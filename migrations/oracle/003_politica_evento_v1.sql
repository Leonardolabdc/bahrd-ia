-- ===========================================================================
-- 003 · Política de elegibilidade v1.0 — os TRÊS tipos de evento em escopo
--
-- Espelha `src/central_ia/domain/eventos.py`. Só estes três existem na POC:
--
--   REMOCAO_BATERIA        elegível   · PB-BATERIA          · janela  90 s
--   MOVIMENTO_SEM_IGNICAO  elegível   · PB-MOV-SEM-IGNICAO  · janela  60 s
--   MOVIMENTO_SEM_IGNICAO  elegível   · confirmação DUPLA (motorista + gestor)
--   PANICO                 INELEGÍVEL · humano exclusivo    · SLA     30 s
--
-- Pânico está EM ESCOPO e é INELEGÍVEL — duas coisas diferentes. Ele entra na
-- fila do operador e a IA nunca fala com ninguém (princípio 3).
--
-- O motor de políticas (Sprint 1) lê daqui, não de constante em código: a
-- supervisão precisa poder desligar um tipo de evento sem esperar um deploy.
-- Toda decisão grava `politica_versao` na trilha de auditoria.
--
-- Novos tipos entram como uma linha nova e uma versão nova, nunca por UPDATE:
-- a versão que produziu cada atendimento tem de continuar reconstruível.
-- ===========================================================================

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos,
  vigente_de, ativo
) VALUES (
  'v1.0', 'REMOCAO_BATERIA', 'ALTA', 'S',
  'LIGACAO', 'PB-BATERIA',
  '{"janela_s": 90,
    "cascata_canais": ["LIGACAO", "AUDIO"],
    "modo_paralelo": true,
    "contatos": ["MOTORISTA", "GESTOR"]}',
  '["chave_geral_desligada_pelo_motorista",
    "veiculo_em_manutencao",
    "falha_de_instalacao_reportada"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos,
  vigente_de, ativo
) VALUES (
  'v1.0', 'MOVIMENTO_SEM_IGNICAO', 'ALTA', 'S',
  'LIGACAO', 'PB-MOV-SEM-IGNICAO',
  '{"janela_s": 60,
    "cascata_canais": ["LIGACAO", "TEXTO"],
    "modo_paralelo": true,
    "requer_confirmacao_dupla": true,
    "contatos": ["MOTORISTA", "GESTOR"]}',
  '["reboque_autorizado",
    "transporte_em_prancha_ou_balsa",
    "falso_positivo_gps"]',
  SYSTIMESTAMP, 'S'
);

-- Lista de desfechos VAZIA, de propósito: a IA não pode fechar pânico com
-- nada. O motor recusa qualquer desfecho que não esteja na lista branca, então
-- lista vazia é a trava, não uma omissão.
INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos,
  vigente_de, ativo
) VALUES (
  'v1.0', 'PANICO', 'CRITICA', 'N',
  NULL, NULL,
  '{"janela_s": 30,
    "cascata_canais": [],
    "motivo_inelegibilidade": "Evento crítico — atendimento exclusivamente humano",
    "leitura_de_contexto": true}',
  '[]',
  SYSTIMESTAMP, 'S'
);

COMMIT;
