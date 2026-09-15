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
    fornecedor_nome: str = None
    palavra_chave: str = None
    conta_codigo: str
    criada_por_ia: bool = False

@router.post("/confirmar")
async def confirmar_classificacao(req: ConfirmarClassificacaoRequest):
    """
    Recebe a confirmação do usuário e insere um registro na tabela regras_contabeis
    para o aprendizado contínuo do motor de classificação.
    """
    try:
        supabase = _get_supabase()
        
        # Inserir no banco
        insert_data = {
            "administradora_id": int(req.administradora_id) if req.administradora_id.isdigit() else 1, # Ajuste temporário se vier string não numérica
            "fornecedor_nome": req.fornecedor_nome,
            "palavra_chave": req.palavra_chave,
            "conta_codigo": req.conta_codigo,
            "criada_por_ia": req.criada_por_ia,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Em supabase-py, a tabela precisa estar criada e acessível
        result = supabase.table("regras_contabeis").insert(insert_data).execute()
        
        return {"ok": True, "message": "Regra contábil salva com sucesso", "data": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar regra contábil: {str(e)}")
