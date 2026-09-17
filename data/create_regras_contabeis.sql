CREATE TABLE regras_contabeis (
    id SERIAL PRIMARY KEY,
    administradora_id UUID NOT NULL,
    conta_codigo VARCHAR(50) NOT NULL,
    contexto TEXT,
    criada_por_ia BOOLEAN DEFAULT FALSE,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT regras_contabeis_admin_conta_key UNIQUE (administradora_id, conta_codigo)
);
