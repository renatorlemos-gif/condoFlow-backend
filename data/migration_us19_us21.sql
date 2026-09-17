-- migration_us19_us21.sql
-- Saneamento de Débito Técnico (US-21) e Preparação para Motor Semântico (US-19)

-- 1. Expurgo da tabela legada baseada em palavras-chave
DROP TABLE IF EXISTS regras_de_para;

-- 2. Garantir que a tabela canônica existe (caso não tenha sido criada)
CREATE TABLE IF NOT EXISTS regras_contabeis (
    id SERIAL PRIMARY KEY,
    administradora_id UUID NOT NULL,
    fornecedor_nome VARCHAR(255),
    conta_codigo VARCHAR(50) NOT NULL,
    criada_por_ia BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Atualizar esquema da tabela regras_contabeis
ALTER TABLE regras_contabeis DROP COLUMN IF EXISTS palavra_chave;
ALTER TABLE regras_contabeis ADD COLUMN IF NOT EXISTS contexto TEXT;
ALTER TABLE regras_contabeis ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- 4. Criar a constraint de unicidade exigida pela US-19 / US-21
ALTER TABLE regras_contabeis DROP CONSTRAINT IF EXISTS regras_contabeis_admin_forn_conta_key;
ALTER TABLE regras_contabeis ADD CONSTRAINT regras_contabeis_admin_forn_conta_key UNIQUE (administradora_id, fornecedor_nome, conta_codigo);
ALTER TABLE balancetes_historicos DROP COLUMN IF EXISTS valor_referencia;

-- 5. Fix type of administradora_id to UUID
ALTER TABLE regras_contabeis DROP CONSTRAINT IF EXISTS regras_contabeis_admin_forn_conta_key;
ALTER TABLE regras_contabeis ALTER COLUMN administradora_id TYPE UUID USING administradora_id::text::uuid;
ALTER TABLE regras_contabeis ADD CONSTRAINT regras_contabeis_admin_forn_conta_key UNIQUE (administradora_id, fornecedor_nome, conta_codigo);