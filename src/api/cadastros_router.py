import os
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/cadastros", tags=["Cadastros BÃ¡sicos"])

def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase nÃ£o configurado.")
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com Supabase: {e}")

# Schemas Administradora
class AdministradoraCreate(BaseModel):
    nome: str
    cnpj: Optional[str] = None
    ativo: Optional[bool] = True

class AdministradoraUpdate(BaseModel):
    nome: Optional[str] = None
    cnpj: Optional[str] = None
    ativo: Optional[bool] = None

class AdministradoraOut(BaseModel):
    id: str
    nome: str
    cnpj: Optional[str] = None
    ativo: bool

# Schemas Condominio
class CondominioCreate(BaseModel):
    administradora_id: str
    nome: str
    cnpj: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    ativo: Optional[bool] = True

class CondominioUpdate(BaseModel):
    nome: Optional[str] = None
    cnpj: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    ativo: Optional[bool] = None

class CondominioOut(BaseModel):
    id: str
    administradora_id: str
    nome: str
    cnpj: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    ativo: bool

# --- Endpoints de Administradoras ---

@router.get("/administradoras", response_model=List[AdministradoraOut])
async def listar_administradoras(ativo: Optional[bool] = None):
    supabase = _get_supabase()
    query = supabase.table("administradoras").select("*")
    if ativo is not None:
        query = query.eq("ativo", ativo)
    res = query.execute()
    return res.data

@router.get("/administradoras/{id}", response_model=AdministradoraOut)
async def obter_administradora(id: str):
    supabase = _get_supabase()
    res = supabase.table("administradoras").select("*").eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Administradora nÃ£o encontrada")
    return res.data[0]

@router.post("/administradoras", response_model=AdministradoraOut)
async def criar_administradora(admin: AdministradoraCreate):
    supabase = _get_supabase()
    res = supabase.table("administradoras").insert(admin.model_dump(exclude_unset=True)).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Erro ao criar administradora")
    return res.data[0]

@router.put("/administradoras/{id}", response_model=AdministradoraOut)
async def atualizar_administradora(id: str, admin: AdministradoraUpdate):
    supabase = _get_supabase()
    res = supabase.table("administradoras").update(admin.model_dump(exclude_unset=True)).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Administradora nÃ£o encontrada")
    return res.data[0]

@router.delete("/administradoras/{id}")
async def excluir_administradora(id: str):
    supabase = _get_supabase()
    res = supabase.table("administradoras").update({"ativo": False}).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Administradora nÃ£o encontrada")
    return {"message": "Administradora desativada com sucesso"}

# --- Endpoints de CondomÃ­nios ---

@router.get("/condominios", response_model=List[CondominioOut])
async def listar_condominios(administradora_id: Optional[str] = None, ativo: Optional[bool] = None):
    supabase = _get_supabase()
    query = supabase.table("condominios").select("*")
    if administradora_id:
        query = query.eq("administradora_id", administradora_id)
    if ativo is not None:
        query = query.eq("ativo", ativo)
    res = query.execute()
    return res.data

@router.get("/condominios/{id}", response_model=CondominioOut)
async def obter_condominio(id: str):
    supabase = _get_supabase()
    res = supabase.table("condominios").select("*").eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="CondomÃ­nio nÃ£o encontrado")
    return res.data[0]

@router.post("/condominios", response_model=CondominioOut)
async def criar_condominio(condo: CondominioCreate):
    supabase = _get_supabase()
    res = supabase.table("condominios").insert(condo.model_dump(exclude_unset=True)).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Erro ao criar condomÃ­nio")
    return res.data[0]

@router.put("/condominios/{id}", response_model=CondominioOut)
async def atualizar_condominio(id: str, condo: CondominioUpdate):
    supabase = _get_supabase()
    res = supabase.table("condominios").update(condo.model_dump(exclude_unset=True)).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="CondomÃ­nio nÃ£o encontrado")
    return res.data[0]

@router.delete("/condominios/{id}")
async def excluir_condominio(id: str):
    supabase = _get_supabase()
    res = supabase.table("condominios").update({"ativo": False}).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="CondomÃ­nio nÃ£o encontrado")
    return {"message": "CondomÃ­nio desativado com sucesso"}

# --- Endpoints de Contas Bancárias ---

class ContaBancariaCreate(BaseModel):
    condominio_id: str
    banco: str
    agencia: str
    conta: str
    plano_conta_id: str
    ativo: Optional[bool] = True

class ContaBancariaOut(BaseModel):
    id: str
    condominio_id: str
    banco: str
    agencia: str
    conta: str
    plano_conta_id: str
    ativo: bool

@router.get("/contas-bancarias", response_model=List[ContaBancariaOut])
async def listar_contas_bancarias(condominio_id: Optional[str] = None, ativo: Optional[bool] = None):
    supabase = _get_supabase()
    query = supabase.table("contas_bancarias").select("*")
    if condominio_id:
        query = query.eq("condominio_id", condominio_id)
    if ativo is not None:
        query = query.eq("ativo", ativo)
    res = query.execute()
    return res.data

@router.post("/contas-bancarias", response_model=ContaBancariaOut)
async def criar_conta_bancaria(conta: ContaBancariaCreate):
    supabase = _get_supabase()
    res = supabase.table("contas_bancarias").insert(conta.model_dump(exclude_unset=True)).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Erro ao criar conta bancaria")
    return res.data[0]

@router.delete("/contas-bancarias/{id}")
async def excluir_conta_bancaria(id: str):
    supabase = _get_supabase()
    res = supabase.table("contas_bancarias").update({"ativo": False}).eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Conta bancaria nao encontrada")
    return {"message": "Conta bancaria desativada com sucesso"}


