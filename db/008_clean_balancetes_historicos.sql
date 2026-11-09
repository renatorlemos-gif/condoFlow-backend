-- ====================================================================
-- CondoFlow v1.59 - Saneamento da tabela balancetes_historicos
-- Operação puramente DML. NÃO remove tabelas nem altera DDL.
-- Totalmente reversível para futuras inserções de balancetes.
-- ====================================================================

TRUNCATE TABLE balancetes_historicos;
