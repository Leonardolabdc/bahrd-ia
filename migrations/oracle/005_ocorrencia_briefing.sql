-- ===========================================================================
-- 005 · Briefing da ocorrência
--
-- É o bloco "O que a IA apurou" da tela do operador: o resumo do atendimento
-- quando a IA conduziu, ou a **leitura de contexto** quando o evento é
-- inelegível e ela não falou com ninguém.
--
-- Não cabia em `desfecho_justificativa`: aquele campo explica o desfecho, e
-- pânico não tem desfecho da IA — tem leitura. Misturar os dois faria a trilha
-- de auditoria sugerir que a IA concluiu algo num evento que ela nunca tocou.
--
-- `briefing_gerado_por_ia` distingue o texto do modelo do texto de reserva
-- montado em código quando a saída é descartada. Sem essa marca, ninguém sabe
-- depois se o operador leu algo escrito por um modelo ou por um `join`.
-- ===========================================================================

ALTER TABLE ocorrencia ADD (
  briefing               CLOB,
  briefing_gerado_por_ia CHAR(1) DEFAULT 'N' CHECK (briefing_gerado_por_ia IN ('S','N'))
);
