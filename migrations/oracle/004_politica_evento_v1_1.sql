-- ===========================================================================
-- 004 · Política de elegibilidade v1.1 — os 11 tipos de evento reais da Bahrd
--
-- Espelha `src/central_ia/domain/eventos.py` (guardado pelo teste
-- tests/test_politica_seed.py, que quebra se os dois divergirem).
--
-- Substitui a v1.0 (3 tipos) pelos rótulos REAIS do sistema da Bahrd.
--
--   ELEGÍVEIS (têm playbook)
--     Remoção de bateria ....................... PB-BATERIA          90 s
--     Movimento com ignição desligada .......... PB-MOV-SEM-IGNICAO  60 s  (dupla)
--     Velocidade excedida ...................... PB-VELOCIDADE      180 s
--     Ultrapassou limite de velocidade ......... PB-VELOCIDADE      180 s
--     Velocidade excedida dentro da cerca ...... PB-VELOCIDADE      180 s
--
--   CRÍTICOS — humano exclusivo, por natureza
--     Pânico ................................... SLA 30 s
--     ATENÇÃO: VEÍCULO COM ROUBO ATIVO ......... SLA 15 s
--
--   EM ESCOPO, INELEGÍVEIS POR ORA — falta playbook ou informação da Bahrd
--     Entrada 2 acionada ....................... significado não mapeado
--     Erro na bateria backup ................... provável ordem de manutenção
--     Entrou na cerca .......................... depende do tipo de cerca
--     Voltou à Cerca de Polígono ............... provável evento de normalização
--
-- Os três de velocidade compartilham `grupo_deduplicacao`: um único excesso
-- pode disparar mais de um deles, e três contatos pelo mesmo fato destroem a
-- credibilidade da central (regra de fadiga de alerta do PB-VELOCIDADE).
--
-- A v1.0 é ENCERRADA (`ativo='N'`, `vigente_ate`), não apagada nem reescrita:
-- a versão que produziu cada atendimento precisa continuar reconstruível.
-- ===========================================================================

UPDATE politica_evento
   SET ativo = 'N', vigente_ate = SYSTIMESTAMP
 WHERE versao = 'v1.0' AND ativo = 'S';

-- ─────────────────────────── Elegíveis ───────────────────────────

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'REMOCAO_BATERIA', 'ALTA', 'S', 'LIGACAO', 'PB-BATERIA',
  '{"rotulo_link": "Remoção de bateria", "janela_s": 90,
    "cascata_canais": ["LIGACAO","AUDIO"], "modo_paralelo": true,
    "contatos": ["MOTORISTA","GESTOR"]}',
  '["chave_geral_desligada_pelo_motorista","veiculo_em_manutencao","falha_de_instalacao_reportada"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'MOVIMENTO_SEM_IGNICAO', 'ALTA', 'S', 'LIGACAO', 'PB-MOV-SEM-IGNICAO',
  '{"rotulo_link": "Movimento com ignição desligada", "janela_s": 60,
    "cascata_canais": ["LIGACAO","TEXTO"], "modo_paralelo": true,
    "requer_confirmacao_dupla": true, "contatos": ["MOTORISTA","GESTOR"]}',
  '["reboque_autorizado","transporte_em_prancha_ou_balsa","falso_positivo_gps"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'VELOCIDADE_EXCEDIDA', 'BAIXA', 'S', 'AUDIO', 'PB-VELOCIDADE',
  '{"rotulo_link": "Velocidade excedida", "janela_s": 180,
    "cascata_canais": ["AUDIO","LIGACAO"], "contatos": ["MOTORISTA"],
    "grupo_deduplicacao": "VELOCIDADE"}',
  '["justificado_pelo_motorista","orientacao_registrada","sem_resposta_orientacao_enviada","problema_mecanico_reportado"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'ULTRAPASSOU_LIMITE_VELOCIDADE', 'BAIXA', 'S', 'AUDIO', 'PB-VELOCIDADE',
  '{"rotulo_link": "Ultrapassou limite de velocidade", "janela_s": 180,
    "cascata_canais": ["AUDIO","LIGACAO"], "contatos": ["MOTORISTA"],
    "grupo_deduplicacao": "VELOCIDADE"}',
  '["justificado_pelo_motorista","orientacao_registrada","sem_resposta_orientacao_enviada","problema_mecanico_reportado"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'VELOCIDADE_EXCEDIDA_CERCA_POLIGONO', 'MEDIA', 'S', 'AUDIO', 'PB-VELOCIDADE',
  '{"rotulo_link": "Velocidade excedida dentro da cerca polígono", "janela_s": 180,
    "cascata_canais": ["AUDIO","LIGACAO"], "contatos": ["MOTORISTA"],
    "grupo_deduplicacao": "VELOCIDADE"}',
  '["justificado_pelo_motorista","orientacao_registrada","sem_resposta_orientacao_enviada","problema_mecanico_reportado"]',
  SYSTIMESTAMP, 'S'
);

-- ──────────────── Críticos — humano exclusivo, por natureza ────────────────
-- Lista de desfechos VAZIA de propósito: o motor recusa qualquer desfecho fora
-- da lista branca, então lista vazia é a trava, não uma omissão.

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'PANICO', 'CRITICA', 'N', NULL, NULL,
  '{"rotulo_link": "Pânico", "janela_s": 30, "cascata_canais": [],
    "leitura_de_contexto": true,
    "motivo_inelegibilidade": "Evento crítico — atendimento exclusivamente humano"}',
  '[]', SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'ROUBO_ATIVO_MOVIMENTO', 'CRITICA', 'N', NULL, NULL,
  '{"rotulo_link": "ATENÇÃO: VEÍCULO COM ROUBO ATIVO SE MOVIMENTOU!", "janela_s": 15,
    "cascata_canais": [], "leitura_de_contexto": true,
    "motivo_inelegibilidade": "Roubo em andamento — atendimento exclusivamente humano"}',
  '[]', SYSTIMESTAMP, 'S'
);

-- ───────── Em escopo, inelegíveis por ora — aguardando definição ─────────

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'ENTRADA_2_ACIONADA', 'ALTA', 'N', NULL, NULL,
  '{"rotulo_link": "Entrada 2 acionada", "janela_s": 60, "cascata_canais": [],
    "motivo_inelegibilidade": "Significado da entrada não mapeado — tratado como alto risco",
    "pendencia": "Existe mapa de qual sensor está ligado na entrada 2, por cliente ou veículo?"}',
  '[]', SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'ERRO_BATERIA_BACKUP', 'MEDIA', 'N', NULL, NULL,
  '{"rotulo_link": "Erro na bateria backup", "janela_s": 600, "cascata_canais": [],
    "motivo_inelegibilidade": "Sem playbook — evento técnico, provavelmente sem contato",
    "pendencia": "Gera contato hoje, ou vira chamado de manutenção?"}',
  '[]', SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'ENTROU_NA_CERCA', 'MEDIA', 'N', NULL, NULL,
  '{"rotulo_link": "Entrou na cerca", "janela_s": 300, "cascata_canais": [],
    "motivo_inelegibilidade": "Sem playbook — significado depende do tipo de cerca",
    "pendencia": "As cercas são de área AUTORIZADA ou de área de RISCO?"}',
  '[]', SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v1.1', 'VOLTOU_CERCA_POLIGONO', 'BAIXA', 'N', NULL, NULL,
  '{"rotulo_link": "Voltou à Cerca de Polígono", "janela_s": 600, "cascata_canais": [],
    "motivo_inelegibilidade": "Sem playbook — provável evento de normalização, sem contato",
    "pendencia": "Deve ENCERRAR a ocorrência de saída anterior em vez de criar uma nova?"}',
  '[]', SYSTIMESTAMP, 'S'
);

COMMIT;
