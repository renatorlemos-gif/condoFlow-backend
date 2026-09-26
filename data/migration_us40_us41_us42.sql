-- US-40: Contas Bancárias
CREATE TABLE IF NOT EXISTS contas_bancarias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id UUID REFERENCES condominios(id) ON DELETE CASCADE,
    banco VARCHAR(100) NOT NULL,
    agencia VARCHAR(20) NOT NULL,
    conta VARCHAR(50) NOT NULL,
    plano_conta_id UUID REFERENCES plano_contas(id),
    ativo BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contas_bancarias_condominio ON contas_bancarias(condominio_id);

-- US-41: Associacao Conta Devedora
ALTER TABLE transacoes_extrato ADD COLUMN IF NOT EXISTS conta_bancaria_id UUID REFERENCES contas_bancarias(id);
ALTER TABLE documentos_fiscais ADD COLUMN IF NOT EXISTS conta_devedora_id UUID REFERENCES plano_contas(id);
