CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE regras_contabeis DROP CONSTRAINT IF EXISTS regras_contabeis_admin_forn_conta_key;
ALTER TABLE regras_contabeis DROP COLUMN IF EXISTS fornecedor_nome;
ALTER TABLE regras_contabeis ADD COLUMN IF NOT EXISTS embedding vector(768);
ALTER TABLE regras_contabeis ADD CONSTRAINT regras_contabeis_admin_conta_key UNIQUE (administradora_id, conta_codigo);

CREATE OR REPLACE FUNCTION match_regras_contabeis(
    query_embedding vector(768),
    match_threshold float,
    match_count int,
    p_administradora_id uuid
)
RETURNS TABLE (
    id int,
    administradora_id uuid,
    conta_codigo varchar,
    contexto text,
    criada_por_ia boolean,
    embedding vector(768),
    created_at timestamp,
    updated_at timestamp,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        regras_contabeis.id,
        regras_contabeis.administradora_id,
        regras_contabeis.conta_codigo,
        regras_contabeis.contexto,
        regras_contabeis.criada_por_ia,
        regras_contabeis.embedding,
        regras_contabeis.created_at,
        regras_contabeis.updated_at,
        1 - (regras_contabeis.embedding <=> query_embedding) AS similarity
    FROM regras_contabeis
    WHERE
        regras_contabeis.administradora_id = p_administradora_id
        AND 1 - (regras_contabeis.embedding <=> query_embedding) > match_threshold
    ORDER BY
        regras_contabeis.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
