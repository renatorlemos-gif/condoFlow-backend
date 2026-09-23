import os
import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from supabase import create_client
import logging
from google import genai

logger = logging.getLogger("plano_contas")

router = APIRouter(prefix="/api/v1/plano-contas", tags=["Plano de Contas"])

def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)

def _generate_embedding(text: str) -> list[float]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurada.")
    client = genai.Client(api_key=api_key)
    response = client.models.embed_content(
        model='gemini-embedding-2',
        contents=text,
    )
    return response.embeddings[0].values

class ContaCreate(BaseModel):
    administradora_id: str
    codigo: str
    descricao: str
    contexto: str

class ContaUpdateContexto(BaseModel):
    contexto: str
    model_config = {
        "extra": "forbid"
    }

@router.post("/")
async def create_conta(conta: ContaCreate):
    try:
        supabase = _get_supabase()
        
        # Valida unicidade
        existing = supabase.table("plano_contas").select("id").eq("administradora_id", conta.administradora_id).eq("codigo", conta.codigo).execute()
        if existing.data:
            raise HTTPException(status_code=409, detail=f"A conta '{conta.codigo}' já se encontra registrada no Plano de Contas da administradora. Contas inativadas não liberam reaproveitamento de código contábil.")
            
        # Gera embedding síncrono
        texto_ancora = f"{conta.descricao} - {conta.contexto}"
        try:
            embedding = _generate_embedding(texto_ancora)
        except Exception as e:
            logger.error(f"Erro ao gerar embedding: {e}")
            raise HTTPException(status_code=503, detail="Falha de rede Gemini. Serviço indisponível para vetorização.")
            
        nova_conta = {
            "administradora_id": conta.administradora_id,
            "codigo": conta.codigo,
            "descricao": conta.descricao,
            "contexto": conta.contexto,
            "embedding": embedding,
            "ativo": True,
            "criada_por_ia": False,
            "updated_at": datetime.datetime.utcnow().isoformat()
        }
        
        res = supabase.table("plano_contas").insert(nova_conta).execute()
        return res.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao criar conta: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{conta_id}/contexto")
async def update_contexto(conta_id: str, update_data: ContaUpdateContexto):
    try:
        supabase = _get_supabase()
        
        conta_res = supabase.table("plano_contas").select("*").eq("id", conta_id).execute()
        if not conta_res.data:
            raise HTTPException(status_code=404, detail="Conta não encontrada.")
            
        conta = conta_res.data[0]
        descricao = conta["descricao"]
        novo_contexto = update_data.contexto
        
        texto_ancora = f"{descricao} - {novo_contexto}"
        try:
            embedding = _generate_embedding(texto_ancora)
        except Exception as e:
            logger.error(f"Erro ao gerar embedding: {e}")
            raise HTTPException(status_code=503, detail="Falha de rede Gemini. Serviço indisponível para vetorização.")
            
        update_payload = {
            "contexto": novo_contexto,
            "embedding": embedding,
            "updated_at": datetime.datetime.utcnow().isoformat()
        }
        
        res = supabase.table("plano_contas").update(update_payload).eq("id", conta_id).execute()
        return res.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao atualizar contexto: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{conta_id}")
async def delete_conta(conta_id: str):
    try:
        supabase = _get_supabase()
        try:
            res = supabase.table("plano_contas").update({"ativo": False}).eq("id", conta_id).execute()
        except Exception as db_err:
            if "ativo" in str(db_err).lower():
                 raise HTTPException(status_code=500, detail="Coluna 'ativo' não existe. Por favor, rode a migration SQL do PRD para adicionar a coluna 'ativo' BOOLEAN DEFAULT TRUE.")
            raise db_err
        
        return {"mensagem": "Conta Excluída com Sucesso e Removida dos Motores RAG"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao inativar conta: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
async def get_plano_contas(administradora_id: str):
    try:
        supabase = _get_supabase()
        response = supabase.table("plano_contas").select("id, codigo, descricao, contexto, updated_at").eq("administradora_id", administradora_id).eq("ativo", True).order("codigo").execute()
        return {"data": response.data}
    except Exception as e:
        logger.error(f"Erro ao buscar plano de contas: {e}")
        if "ativo" in str(e).lower():
             raise HTTPException(status_code=500, detail="Coluna 'ativo' não existe. Por favor, rode a migration SQL do PRD para adicionar a coluna 'ativo' BOOLEAN DEFAULT TRUE.")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar plano de contas.")
