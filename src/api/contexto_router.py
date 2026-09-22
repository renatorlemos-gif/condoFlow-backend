"""
contexto_router.py
==================
Endpoints para gerenciamento de contexto Multi-Administradora e Carteira de Condomínios.
Atende a US-01 (RF-01 e RNF-01).

GET  /api/v1/contexto/administradoras — lista as administradoras cadastradas
GET  /api/v1/contexto/condominios     — lista condomínios filtrados por administradora
"""

import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/contexto", tags=["Contexto Multi-Administradora"])

def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None

# Schemas
class AdministradoraResponse(BaseModel):
    id: str
    nome: str
    cnpj: Optional[str] = None
    total_condominios: int = 0

class CondominioResponse(BaseModel):
    id: str
    administradora_id: str
    nome: str
    cnpj: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None

@router.get("/administradoras", response_model=list[AdministradoraResponse])
async def listar_administradoras():
    """Retorna a lista de administradoras ativas."""
    supabase = _get_supabase()
    if supabase:
        try:
            res = supabase.table("administradoras").select("*").eq("ativo", True).execute()
            if res.data:
                return res.data
        except Exception:
            pass
    return []

@router.get("/condominios", response_model=list[CondominioResponse])
async def listar_condominios(administradora_id: Optional[str] = Query(None)):
    """Retorna os condomínios da carteira, opcionalmente filtrados por administradora."""
    supabase = _get_supabase()
    if supabase:
        try:
            query = supabase.table("condominios").select("*").eq("ativo", True)
            if administradora_id:
                query = query.eq("administradora_id", administradora_id)
            res = query.execute()
            if res.data:
                return res.data
        except Exception:
            pass

    return []

class CompetenciasResponse(BaseModel):
    condominio_id: str
    competencias: list[str]
    ultima_competencia: Optional[str] = None

@router.get("/competencias", response_model=CompetenciasResponse)
async def listar_competencias(condominio_id: str = Query(..., description="ID do condomínio")):
    """Retorna as competências (YYYY-MM) com transações disponíveis, ordenadas descrescente."""
    supabase = _get_supabase()
    if supabase:
        try:
            # Busca apenas a data das transações deste condomínio para agregação
            res = supabase.table("transacoes_extrato").select("data_transacao").eq("condominio_id", condominio_id).execute()
            if res.data:
                competencias_set = set()
                for item in res.data:
                    dt = item.get("data_transacao")
                    if dt and len(dt) >= 7:
                        competencias_set.add(dt[:7]) # Extrai YYYY-MM
                
                competencias = sorted(list(competencias_set), reverse=True)
                ultima = competencias[0] if competencias else None
                
                return CompetenciasResponse(
                    condominio_id=condominio_id,
                    competencias=competencias,
                    ultima_competencia=ultima
                )
        except Exception as e:
            print(f"Erro ao buscar competencias: {e}")
            pass

    return CompetenciasResponse(
        condominio_id=condominio_id,
        competencias=[],
        ultima_competencia=None
    )

