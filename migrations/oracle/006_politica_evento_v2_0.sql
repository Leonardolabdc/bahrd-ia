-- ===========================================================================
-- 006 · Política de elegibilidade v2.0 — a barreira passa a ser a evidência
--
-- Espelha `src/central_ia/domain/eventos.py` (guardado pelo teste
-- tests/test_politica_seed.py, que quebra se os dois divergirem).
--
-- O QUE MUDA EM RELAÇÃO À v1.1
--
--   Até a v1.1, evento crítico nunca chegava à IA: a barreira era o *tipo* do
--   evento. Na v2.0 a barreira é a *evidência*. A IA trata todos os tipos,
--   inclusive Pânico e Roubo ativo — mas nos críticos ela é obrigada a
--   classificar ANTES de qualquer contato, e devolve uma probabilidade de o
--   caso ser real:
--
--       probabilidade >= 90  →  humano assume, sem nenhum contato automático
--       probabilidade <  90  →  a IA conduz pelo PB-PANICO
--
--   O limiar de 90 é decisão da operação, não do modelo. Ele vive em
--   `domain/eventos.py` como LIMIAR_ESCALONAMENTO e vai para a trilha de
--   auditoria junto de toda decisão que produziu.
--
--   ELEGÍVEIS COM CONTATO DIRETO
--     Remoção de bateria ....................... PB-BATERIA          90 s
--     Movimento com ignição desligada .......... PB-MOV-SEM-IGNICAO  60 s  (dupla)
--     Velocidade excedida ...................... PB-VELOCIDADE      180 s
--     Ultrapassou limite de velocidade ......... PB-VELOCIDADE      180 s
--     Velocidade excedida dentro da cerca ...... PB-VELOCIDADE      180 s
--
--   ELEGÍVEIS COM TRIAGEM PRÉVIA OBRIGATÓRIA  ◄── novo na v2.0
--     Pânico ................................... PB-PANICO           30 s
--     ATENÇÃO: VEÍCULO COM ROUBO ATIVO ......... PB-PANICO           15 s
--
--     Roubo ativo entra com `desfechos_permitidos` VAZIO de propósito: é
--     elegível pela mesma regra dos outros, e na prática a triagem sempre o
--     manda para o humano (o veículo já está marcado como roubado). A lista
--     vazia é o cinto de segurança embaixo disso — mesmo que a triagem
--     errasse, a IA não teria com o que fechar.
--
--   EM ESCOPO, INELEGÍVEIS — falta playbook ou informação da Bahrd
--     Entrada 2 acionada ....................... significado não mapeado
--     Erro na bateria backup ................... provável ordem de manutenção
--     Entrou na cerca .......................... depende do tipo de cerca
--     Voltou à Cerca de Polígono ............... provável evento de normalização
--
--     Estes quatro continuam fora não por decisão de política, mas por falta
--     de informação: ninguém sabe ainda qual é o procedimento. É pergunta em
--     aberto com a Bahrd, não escolha de produto.
--
-- A v1.1 é ENCERRADA (`ativo='N'`, `vigente_ate`), não apagada nem reescrita:
-- a versão que produziu cada atendimento precisa continuar reconstruível.
-- ===========================================================================

UPDATE politica_evento
   SET ativo = 'N', vigente_ate = SYSTIMESTAMP
 WHERE versao = 'v1.1' AND ativo = 'S';

-- ──────────────────── Elegíveis, contato direto ────────────────────

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'REMOCAO_BATERIA', 'ALTA', 'S', 'LIGACAO', 'PB-BATERIA',
  '{"rotulo_link": "Remoção de bateria", "janela_s": 90,
    "cascata_canais": ["LIGACAO","AUDIO"], "modo_paralelo": true,
    "exige_triagem_previa": false,
    "contatos": ["MOTORISTA","GESTOR"]}',
  '["chave_geral_desligada_pelo_motorista","veiculo_em_manutencao","falha_de_instalacao_reportada"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'MOVIMENTO_SEM_IGNICAO', 'ALTA', 'S', 'LIGACAO', 'PB-MOV-SEM-IGNICAO',
  '{"rotulo_link": "Movimento com ignição desligada", "janela_s": 60,
    "cascata_canais": ["LIGACAO","TEXTO"], "modo_paralelo": true,
    "exige_triagem_previa": false,
    "requer_confirmacao_dupla": true, "contatos": ["MOTORISTA","GESTOR"]}',
  '["reboque_autorizado","transporte_em_prancha_ou_balsa","falso_positivo_gps"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'VELOCIDADE_EXCEDIDA', 'BAIXA', 'S', 'AUDIO', 'PB-VELOCIDADE',
  '{"rotulo_link": "Velocidade excedida", "janela_s": 180,
    "cascata_canais": ["AUDIO","LIGACAO"], "contatos": ["MOTORISTA"],
    "exige_triagem_previa": false,
    "grupo_deduplicacao": "VELOCIDADE"}',
  '["justificado_pelo_motorista","orientacao_registrada","sem_resposta_orientacao_enviada","problema_mecanico_reportado"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'ULTRAPASSOU_LIMITE_VELOCIDADE', 'BAIXA', 'S', 'AUDIO', 'PB-VELOCIDADE',
  '{"rotulo_link": "Ultrapassou limite de velocidade", "janela_s": 180,
    "cascata_canais": ["AUDIO","LIGACAO"], "contatos": ["MOTORISTA"],
    "exige_triagem_previa": false,
    "grupo_deduplicacao": "VELOCIDADE"}',
  '["justificado_pelo_motorista","orientacao_registrada","sem_resposta_orientacao_enviada","problema_mecanico_reportado"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'VELOCIDADE_EXCEDIDA_CERCA_POLIGONO', 'MEDIA', 'S', 'AUDIO', 'PB-VELOCIDADE',
  '{"rotulo_link": "Velocidade excedida dentro da cerca polígono", "janela_s": 180,
    "cascata_canais": ["AUDIO","LIGACAO"], "contatos": ["MOTORISTA"],
    "exige_triagem_previa": false,
    "grupo_deduplicacao": "VELOCIDADE"}',
  '["justificado_pelo_motorista","orientacao_registrada","sem_resposta_orientacao_enviada","problema_mecanico_reportado"]',
  SYSTIMESTAMP, 'S'
);

-- ─────────── Elegíveis com triagem prévia obrigatória (novo) ───────────
-- `limiar_escalonamento` fica registrado na política, e não só no código: é o
-- número que explica, meses depois, por que aquele caso foi para o humano.

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'PANICO', 'CRITICA', 'S', 'LIGACAO', 'PB-PANICO',
  '{"rotulo_link": "Pânico", "janela_s": 30,
    "cascata_canais": ["LIGACAO","TEXTO"], "contatos": ["MOTORISTA","GESTOR"],
    "exige_triagem_previa": true, "limiar_escalonamento": 90,
    "regra": "Nenhum contato antes de classificar. Acima do limiar, humano assume sem contato."}',
  '["acionamento_acidental_confirmado","alarme_falso_confirmado_por_triagem"]',
  SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'ROUBO_ATIVO_MOVIMENTO', 'CRITICA', 'S', 'LIGACAO', 'PB-PANICO',
  '{"rotulo_link": "ATENÇÃO: VEÍCULO COM ROUBO ATIVO SE MOVIMENTOU!", "janela_s": 15,
    "cascata_canais": ["LIGACAO"], "contatos": ["GESTOR"],
    "exige_triagem_previa": true, "limiar_escalonamento": 90,
    "regra": "Veículo já marcado como roubado entra alto na triagem e vai para o humano. Lista branca vazia impede fechamento pela IA em qualquer cenário."}',
  '[]', SYSTIMESTAMP, 'S'
);

-- ───────── Em escopo, inelegíveis — aguardando definição da Bahrd ─────────

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'ENTRADA_2_ACIONADA', 'ALTA', 'N', NULL, NULL,
  '{"rotulo_link": "Entrada 2 acionada", "janela_s": 60, "cascata_canais": [],
    "motivo_inelegibilidade": "Significado da entrada não mapeado — tratado como alto risco",
    "pendencia": "Existe mapa de qual sensor está ligado na entrada 2, por cliente ou veículo?"}',
  '[]', SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'ERRO_BATERIA_BACKUP', 'MEDIA', 'N', NULL, NULL,
  '{"rotulo_link": "Erro na bateria backup", "janela_s": 600, "cascata_canais": [],
    "motivo_inelegibilidade": "Sem playbook — evento técnico, provavelmente sem contato",
    "pendencia": "Gera contato hoje, ou vira chamado de manutenção?"}',
  '[]', SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'ENTROU_NA_CERCA', 'MEDIA', 'N', NULL, NULL,
  '{"rotulo_link": "Entrou na cerca", "janela_s": 300, "cascata_canais": [],
    "motivo_inelegibilidade": "Sem playbook — significado depende do tipo de cerca",
    "pendencia": "As cercas são de área AUTORIZADA ou de área de RISCO?"}',
  '[]', SYSTIMESTAMP, 'S'
);

INSERT INTO politica_evento (
  versao, tipo_evento, criticidade, elegivel_ia,
  canal_preferido, playbook_codigo, condicoes, desfechos_permitidos, vigente_de, ativo
) VALUES (
  'v2.0', 'VOLTOU_CERCA_POLIGONO', 'BAIXA', 'N', NULL, NULL,
  '{"rotulo_link": "Voltou à Cerca de Polígono", "janela_s": 600, "cascata_canais": [],
    "motivo_inelegibilidade": "Sem playbook — provável evento de normalização, sem contato",
    "pendencia": "Deve ENCERRAR a ocorrência de saída anterior em vez de criar uma nova?"}',
  '[]', SYSTIMESTAMP, 'S'
);

COMMIT;
