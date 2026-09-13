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

# Dados padrão (carteira das duas administradoras) caso ainda não estejam no Supabase
ADMINISTRADORAS_DEFAULT = [
    {
        "id": "adm-alpha",
        "nome": "Administradora Alpha Condomínios",
        "cnpj": "12.345.678/0001-90",
        "total_condominios": 3,
    },
    {
        "id": "adm-beta",
        "nome": "Administradora Beta Gestão Predial",
        "cnpj": "98.765.432/0001-10",
        "total_condominios": 2,
    },
]

CONDOMINIOS_DEFAULT = [
    {
        "id": "condo-alpha-01",
        "administradora_id": "adm-alpha",
        "nome": "Residencial Vista Verde",
        "cnpj": "01.111.222/0001-33",
        "cidade": "São Paulo",
        "uf": "SP",
    },
    {
        "id": "condo-alpha-02",
        "administradora_id": "adm-alpha",
        "nome": "Condomínio Edifício Solar das Acácias",
        "cnpj": "02.222.333/0001-44",
        "cidade": "São Paulo",
        "uf": "SP",
    },
    {
        "id": "condo-alpha-03",
        "administradora_id": "adm-alpha",
        "nome": "Parque das Flores Residencial",
        "cnpj": "03.333.444/0001-55",
        "cidade": "Campinas",
        "uf": "SP",
    },
    {
        "id": "condo-beta-01",
        "administradora_id": "adm-beta",
        "nome": "Edifício Metropolitan Plaza",
        "cnpj": "04.444.555/0001-66",
        "cidade": "Santos",
        "uf": "SP",
    },
    {
        "id": "condo-beta-02",
        "administradora_id": "adm-beta",
        "nome": "Residencial Jardins do Bosque",
        "cnpj": "05.555.666/0001-77",
        "cidade": "São Bernardo do Campo",
        "uf": "SP",
    },
]

@router.get("/administradoras", response_model=list[AdministradoraResponse])
async def listar_administradoras():
    """Retorna a lista de administradoras ativas."""
    supabase = _get_supabase()
    if supabase:
        try:
            res = supabase.table("administradoras").select("*").execute()
            if res.data and len(res.data) > 0:
                return res.data
        except Exception:
            pass
    return ADMINISTRADORAS_DEFAULT

@router.get("/condominios", response_model=list[CondominioResponse])
async def listar_condominios(administradora_id: Optional[str] = Query(None)):
    """Retorna os condomínios da carteira, opcionalmente filtrados por administradora."""
    supabase = _get_supabase()
    if supabase:
        try:
            query = supabase.table("condominios").select("*")
            if administradora_id:
                query = query.eq("administradora_id", administradora_id)
            res = query.execute()
            if res.data and len(res.data) > 0:
                return res.data
        except Exception:
            pass

    if administradora_id:
        return [c for c in CONDOMINIOS_DEFAULT if c["administradora_id"] == administradora_id]
    return CONDOMINIOS_DEFAULT
