CREATE TABLE IF NOT EXISTS balancetes_historicos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id TEXT NOT NULL,
    administradora_id TEXT NOT NULL,
    fornecedor_nome TEXT NOT NULL,
    conta_codigo TEXT,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE balancetes_historicos ADD COLUMN IF NOT EXISTS processado_ia BOOLEAN DEFAULT FALSE;
