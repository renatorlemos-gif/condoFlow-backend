-- Script para criar tabelas de Cadastros Básicos (US-05)

CREATE TABLE IF NOT EXISTS administradoras (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome VARCHAR(255) NOT NULL,
    cnpj VARCHAR(20),
    ativo BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS condominios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    administradora_id UUID REFERENCES administradoras(id) ON DELETE CASCADE,
    nome VARCHAR(255) NOT NULL,
    cnpj VARCHAR(20),
    cidade VARCHAR(100),
    uf VARCHAR(2),
    ativo BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index para buscas mais rápidas
CREATE INDEX IF NOT EXISTS idx_condominios_administradora ON condominios(administradora_id);
