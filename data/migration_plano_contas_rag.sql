-- 1. Adicionar colunas RAG no plano_contas
ALTER TABLE plano_contas ADD COLUMN IF NOT EXISTS contexto TEXT;
ALTER TABLE plano_contas ADD COLUMN IF NOT EXISTS criada_por_ia BOOLEAN DEFAULT FALSE;
ALTER TABLE plano_contas ADD COLUMN IF NOT EXISTS embedding vector(768);
ALTER TABLE plano_contas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now());

-- 2. Migrar dados da tabela antiga (se houver) para o plano de contas
-- (Considerando que regras_contabeis usa VARCHAR e plano_contas usa VARCHAR para codigo)
-- Usaremos UPDATE
UPDATE plano_contas pc
SET 
    contexto = rc.contexto,
    criada_por_ia = rc.criada_por_ia,
    embedding = rc.embedding,
    updated_at = rc.updated_at
FROM regras_contabeis rc
WHERE pc.administradora_id = rc.administradora_id::varchar 
  AND pc.codigo = rc.conta_codigo;

-- 3. Inserir contas que por ventura estavam em regras_contabeis mas não no plano_contas
INSERT INTO plano_contas (administradora_id, codigo, descricao, contexto, criada_por_ia, embedding, updated_at)
SELECT 
    rc.administradora_id::varchar, 
    rc.conta_codigo, 
    COALESCE(rc.contexto, 'Conta Contábil'),
    rc.contexto,
    rc.criada_por_ia,
    rc.embedding,
    rc.updated_at
FROM regras_contabeis rc
WHERE NOT EXISTS (
    SELECT 1 FROM plano_contas pc 
    WHERE pc.administradora_id = rc.administradora_id::varchar AND pc.codigo = rc.conta_codigo
);

-- 4. Criar a nova função RPC
CREATE OR REPLACE FUNCTION match_plano_contas(
    query_embedding vector(768),
    match_threshold float,
    match_count int,
    p_administradora_id varchar
)
RETURNS TABLE (
    id uuid,
    administradora_id varchar,
    codigo varchar,
    descricao varchar,
    contexto text,
    criada_por_ia boolean,
    embedding vector(768),
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        pc.id,
        pc.administradora_id,
        pc.codigo,
        pc.descricao,
        pc.contexto,
        pc.criada_por_ia,
        pc.embedding,
        pc.created_at,
        pc.updated_at,
        1 - (pc.embedding <=> query_embedding) AS similarity
    FROM plano_contas pc
    WHERE
        pc.administradora_id = p_administradora_id
        AND pc.embedding IS NOT NULL
        AND 1 - (pc.embedding <=> query_embedding) > match_threshold
    ORDER BY
        pc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- 5. Drop da tabela antiga e função antiga
DROP FUNCTION IF EXISTS match_regras_contabeis;
DROP TABLE IF EXISTS regras_contabeis;
