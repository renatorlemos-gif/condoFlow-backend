from pydantic import BaseModel, Field
from enum import Enum
from src.utils.documento_parser import DadosExtraidosDTO

class OrigemSugestaoEnum(str, Enum):
    HISTORICO_FORNECEDOR = "HISTORICO_FORNECEDOR"
    PLANO_CONTAS_TEXTO = "PLANO_CONTAS_TEXTO"
    DEFAULT = "DEFAULT"

class SugestaoContabilDTO(BaseModel):
    conta_debito_codigo: str
    conta_debito_nome: str
    conta_credito_codigo: str
    conta_credito_nome: str
    historico_sugerido: str
    score_confianca: float = Field(..., ge=0.0, le=1.0)
    origem_sugestao: OrigemSugestaoEnum

class ConhecimentoService:
    def __init__(self, db_context=None):
        self.db = db_context

    async def buscar_historico_fornecedor(self, cnpj_cpf: str, condomino_id: str) -> dict | None:
        """
        Consulta na base se já existe lançamento aprovado para este CNPJ/CPF.
        """
        if not cnpj_cpf or not self.db:
            return None
        
        # Exemplo de consulta: buscar o último lançamento validado deste CNPJ
        # return await self.db.lancamentos.find_one({"cnpj_cpf": cnpj_cpf, "condominio_id": condomino_id})
        return None

    async def gerar_sugestao(self, dados: DadosExtraidosDTO, condomino_id: str) -> SugestaoContabilDTO:
        # 1. Tenta buscar por histórico do fornecedor (Match exato por CNPJ)
        historico = await self.buscar_historico_fornecedor(dados.cnpj_cpf_fornecedor, condomino_id)
        
        if historico:
            return SugestaoContabilDTO(
                conta_debito_codigo=historico["conta_debito_codigo"],
                conta_debito_nome=historico["conta_debito_nome"],
                conta_credito_codigo=historico["conta_credito_codigo"],
                conta_credito_nome=historico["conta_credito_nome"],
                historico_sugerido=f"Vlr. ref. {dados.descricao or 'serviços prestados'} - {dados.nome_fornecedor or ''}",
                score_confianca=0.98,
                origem_sugestao=OrigemSugestaoEnum.HISTORICO_FORNECEDOR
            )

        # 2. Caso não tenha histórico, aplica fallback padrão ou busca semântica no plano de contas
        return SugestaoContabilDTO(
            conta_debito_codigo="3.1.09.99",
            conta_debito_nome="Despesas Diversas / A Classificar",
            conta_credito_codigo="1.1.01.02",
            conta_credito_nome="Banco Conta Movimento",
            historico_sugerido=f"Pagamento referente a {dados.descricao or 'despesa em análise'}",
            score_confianca=0.50,
            origem_sugestao=OrigemSugestaoEnum.DEFAULT
        )