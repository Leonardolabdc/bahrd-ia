-- ===========================================================================
-- 002 · Índice vetorial da base de conhecimento
--
-- Separado do 001 de propósito: é o único DDL do projeto cujo tipo de índice
-- difere entre o container local e o ADB-S.
--
--   Local (Oracle Free)  → IVF (ORGANIZATION NEIGHBOR PARTITIONS).
--                          Não exige `vector_memory_size`, que só se configura
--                          com ALTER SYSTEM — privilégio que a aplicação não
--                          tem, por decisão (armadilha 1).
--   ADB-S (Fase 2)       → HNSW (ORGANIZATION INMEMORY NEIGHBOR GRAPH),
--                          melhor recall com o vector pool já provisionado.
--
-- O tipo vem de ${TIPO_INDICE_VETORIAL}. A consulta com pré-filtro do RAG
-- (doc 02 §5.1) é idêntica nos dois — só muda a estrutura por baixo.
-- ===========================================================================

CREATE VECTOR INDEX ix_kb_chunk_vec ON kb_chunk (embedding)
  ORGANIZATION ${TIPO_INDICE_VETORIAL}
  DISTANCE COSINE
  WITH TARGET ACCURACY 95;
