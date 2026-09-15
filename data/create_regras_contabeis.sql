CREATE TABLE regras_contabeis (
    id SERIAL PRIMARY KEY,
    administradora_id INT NOT NULL,
    fornecedor_nome VARCHAR(255),
    palavra_chave VARCHAR(255),
    conta_codigo VARCHAR(50) NOT NULL,
    criada_por_ia BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
