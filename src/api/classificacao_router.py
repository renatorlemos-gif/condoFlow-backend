import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from supabase import create_client
from datetime import datetime, timezone

router = APIRouter(prefix="/api/classificacao", tags=["Classificação Contábil"])

def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)

class ConfirmarClassificacaoRequest(BaseModel):
    administradora_id: str
    conta_codigo: str
    criada_por_ia: bool = False

@router.post("/confirmar")
async def confirmar_classificacao(req: ConfirmarClassificacaoRequest):
    """
    Rota legada para confirmação manual (agora tratada em validacao_router.py).
    Mantida por retrocompatibilidade de API, retorna sucesso sem sobrescrever o plano de contas.
    """
    try:
        # A inteligência semântica foi movida para o hook de validação em validacao_router.py.
        # Não sobrescrevemos mais a tabela plano_contas cegamente por aqui.

        
        return {"ok": True, "message": "Plano de contas atualizado com sucesso", "data": {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar regra contábil: {str(e)}")
