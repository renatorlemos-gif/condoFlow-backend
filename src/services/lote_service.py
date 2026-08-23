from uuid import uuid4
from typing import List
from pydantic import BaseModel

from src.utils.documento_parser import DadosExtraidosDTO
from src.services.conhecimento_service import SugestaoContabilDTO

class ItemLoteContabil(BaseModel):
    id: str
    condominio_id: str
    hash_documento: str
    data_movimento: str
    valor: float
    conta_debito_codigo: str
    conta_credito_codigo: str
    historico: str
    cnpj_fornecedor: str | None = None
    nome_fornecedor: str | None = None

class LoteService:
    def __init__(self, db_context=None):
        self.db = db_context

    async def adicionar_item(self, condomino_id: str, dados: DadosExtraidosDTO, sugestao: SugestaoContabilDTO, hash_doc: str) -> ItemLoteContabil:
        novo_item = ItemLoteContabil(
            id=str(uuid4()),
            condominio_id=condomino_id,
            hash_documento=hash_doc,
            data_movimento=dados.data_pagamento or dados.data_vencimento or "2026-08-23",
            valor=dados.valor_total,
            conta_debito_codigo=sugestao.conta_debito_codigo,
            conta_credito_codigo=sugestao.conta_credito_codigo,
            historico=sugestao.historico_sugerido,
            cnpj_fornecedor=dados.cnpj_cpf_fornecedor,
            nome_fornecedor=dados.nome_fornecedor
        )
        
        # Persiste no banco ou estrutura em memória
        # await self.db.lotes.insert(novo_item.dict())
        return novo_item

    async def exportar_lote_csv(self, items: List[ItemLoteContabil]) -> str:
        """Gera a string CSV formatada para o sistema de destino."""
        header = "DATA;CONTA_DEBITO;CONTA_CREDITO;VALOR;HISTORICO;CNPJ\n"
        linhas = [
            f"{item.data_movimento};{item.conta_debito_codigo};{item.conta_credito_codigo};{item.valor:.2f};{item.historico};{item.cnpj_fornecedor or ''}"
            for item in items
        ]
        return header + "\n".join(linhas)