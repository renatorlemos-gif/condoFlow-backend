-- SQL script para criar a tabela de Plano de Contas
-- US-03A: Gestão do Plano de Contas (Nível Administradora)

CREATE TABLE IF NOT EXISTS public.plano_contas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    administradora_id VARCHAR(255) NOT NULL,
    codigo VARCHAR(50) NOT NULL,
    descricao VARCHAR(255) NOT NULL,
    tipo VARCHAR(50) DEFAULT 'analitica',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
    CONSTRAINT unique_adm_codigo UNIQUE (administradora_id, codigo)
);

-- Políticas de segurança (opcional, dependendo de como o RLS está configurado no projeto)
-- ALTER TABLE public.plano_contas ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Acesso total" ON public.plano_contas FOR ALL USING (true);
