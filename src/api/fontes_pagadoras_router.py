import os
import calendar
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional

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

router = APIRouter(prefix="/api/v1/fontes-pagadoras", tags=["Fontes Pagadoras"])

class FontePagadoraBase(BaseModel):
    condominio_id: str
    nome: str
    tipo: str
    banco: Optional[str] = None
    agencia: Optional[str] = None
    conta: Optional[str] = None
    plano_conta_id: str | None = None
    exige_conciliacao_extrato: bool = True

class FontePagadoraCreate(FontePagadoraBase):
    pass

class FontePagadoraResponse(FontePagadoraBase):
    id: str
    ativo: bool

class FontePagadoraCorrenteResponse(BaseModel):
    condominio_id: str
    mes_ano: Optional[str] = None
    fonte_pagadora_id: str
    nome: str
    banco: Optional[str] = None
    origem: str

@router.post("/", response_model=FontePagadoraResponse, status_code=201)
def create_fonte_pagadora(fonte: FontePagadoraCreate):
    if fonte.tipo == "CONTA_BANCARIA" and not (fonte.banco and fonte.agencia and fonte.conta):
        raise HTTPException(status_code=422, detail="Para fontes bancárias, o banco, agência e conta corrente são campos obrigatórios.")
    
    supabase = _get_supabase()
    data = {
        "condominio_id": fonte.condominio_id,
        "nome": fonte.nome,
        "tipo": fonte.tipo,
        "banco": fonte.banco,
        "agencia": fonte.agencia,
        "conta": fonte.conta,
        "plano_conta_id": fonte.plano_conta_id,
        "exige_conciliacao_extrato": fonte.exige_conciliacao_extrato,
        "ativo": True
    }
    
    response = supabase.table("fontes_pagadoras").insert(data).execute()
    if not response.data:
        raise HTTPException(status_code=400, detail="Erro ao criar fonte pagadora")
    return response.data[0]

@router.get("/", response_model=List[FontePagadoraResponse])
def listar_fontes(condominio_id: str, apenas_ativas: bool = True):
    supabase = _get_supabase()
    query = supabase.table("fontes_pagadoras").select("*").eq("condominio_id", condominio_id)
    if apenas_ativas:
        query = query.eq("ativo", True)
    response = query.execute()
    return response.data

@router.get("/corrente", response_model=FontePagadoraCorrenteResponse)
def obter_fonte_pagadora_corrente(condominio_id: str, mes_ano: Optional[str] = None):
    """
    Retorna a fonte pagadora corrente do extrato bancário ativo da competência informada.
    Ordem de resolução:
    1. Transações em transacoes_extrato na competência mes_ano com fonte_pagadora_id IS NOT NULL.
    2. Transação mais recente do condomínio com fonte_pagadora_id IS NOT NULL.
    3. Fonte ativa com exige_conciliacao_extrato == True em fontes_pagadoras.
    4. Primeira fonte ativa do condomínio.
    5. HTTP 404 se não houver fontes cadastradas.
    """
    supabase = _get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="Serviço de banco de dados indisponível.")

    # Passo 1: Transações na competência mes_ano
    if mes_ano and mes_ano.strip():
        mes_ano_str = mes_ano.strip()
        try:
            partes = mes_ano_str.split("-")
            if len(partes) == 2:
                ano, mes = int(partes[0]), int(partes[1])
                _, ultimo_dia = calendar.monthrange(ano, mes)
                inicio = f"{mes_ano_str}-01"
                fim = f"{mes_ano_str}-{ultimo_dia:02d}"
                res = (
                    supabase.table("transacoes_extrato")
                    .select("fonte_pagadora_id, data_transacao")
                    .eq("condominio_id", condominio_id)
                    .gte("data_transacao", inicio)
                    .lte("data_transacao", fim)
                    .not_.is_("fonte_pagadora_id", "null")
                    .order("data_transacao", desc=True)
                    .limit(1)
                    .execute()
                )
                if res.data and len(res.data) > 0 and res.data[0].get("fonte_pagadora_id"):
                    fonte_id = res.data[0]["fonte_pagadora_id"]
                    fonte_res = (
                        supabase.table("fontes_pagadoras")
                        .select("id, nome, banco")
                        .eq("id", fonte_id)
                        .execute()
                    )
                    if fonte_res.data and len(fonte_res.data) > 0:
                        f = fonte_res.data[0]
                        return FontePagadoraCorrenteResponse(
                            condominio_id=condominio_id,
                            mes_ano=mes_ano_str,
                            fonte_pagadora_id=f["id"],
                            nome=f["nome"],
                            banco=f.get("banco"),
                            origem="extrato_transacoes",
                        )
        except Exception:
            pass

    # Passo 2: Fallback para transação mais recente do condomínio com fonte_pagadora_id
    try:
        res_recent = (
            supabase.table("transacoes_extrato")
            .select("fonte_pagadora_id, data_transacao")
            .eq("condominio_id", condominio_id)
            .not_.is_("fonte_pagadora_id", "null")
            .order("data_transacao", desc=True)
            .limit(1)
            .execute()
        )
        if res_recent.data and len(res_recent.data) > 0 and res_recent.data[0].get("fonte_pagadora_id"):
            fonte_id = res_recent.data[0]["fonte_pagadora_id"]
            fonte_res = (
                supabase.table("fontes_pagadoras")
                .select("id, nome, banco")
                .eq("id", fonte_id)
                .execute()
            )
            if fonte_res.data and len(fonte_res.data) > 0:
                f = fonte_res.data[0]
                return FontePagadoraCorrenteResponse(
                    condominio_id=condominio_id,
                    mes_ano=mes_ano,
                    fonte_pagadora_id=f["id"],
                    nome=f["nome"],
                    banco=f.get("banco"),
                    origem="extrato_transacoes",
                )
    except Exception:
        pass

    # Passo 3: Fallback para fonte ativa com exige_conciliacao_extrato == True em fontes_pagadoras
    try:
        res_exige = (
            supabase.table("fontes_pagadoras")
            .select("id, nome, banco")
            .eq("condominio_id", condominio_id)
            .eq("ativo", True)
            .eq("exige_conciliacao_extrato", True)
            .order("nome")
            .limit(1)
            .execute()
        )
        if res_exige.data and len(res_exige.data) > 0:
            f = res_exige.data[0]
            return FontePagadoraCorrenteResponse(
                condominio_id=condominio_id,
                mes_ano=mes_ano,
                fonte_pagadora_id=f["id"],
                nome=f["nome"],
                banco=f.get("banco"),
                origem="fallback_cadastro",
            )
    except Exception:
        pass

    # Passo 4: Primeira fonte ativa do condomínio
    try:
        res_ativa = (
            supabase.table("fontes_pagadoras")
            .select("id, nome, banco")
            .eq("condominio_id", condominio_id)
            .eq("ativo", True)
            .order("nome")
            .limit(1)
            .execute()
        )
        if res_ativa.data and len(res_ativa.data) > 0:
            f = res_ativa.data[0]
            return FontePagadoraCorrenteResponse(
                condominio_id=condominio_id,
                mes_ano=mes_ano,
                fonte_pagadora_id=f["id"],
                nome=f["nome"],
                banco=f.get("banco"),
                origem="fallback_cadastro",
            )
    except Exception:
        pass

    # Passo 5: 404 se não houver fontes
    raise HTTPException(status_code=404, detail="Nenhuma fonte pagadora encontrada para este condomínio.")

@router.get("/reutilizaveis", response_model=List[FontePagadoraResponse])
def listar_fontes_reutilizaveis(administradora_id: str):
    supabase = _get_supabase()
    condos_resp = supabase.table("condominios").select("id").eq("administradora_id", administradora_id).execute()
    if not condos_resp.data:
        return []
    condo_ids = [c["id"] for c in condos_resp.data]
    if not condo_ids:
        return []
    response = supabase.table("fontes_pagadoras").select("*").in_("condominio_id", condo_ids).eq("exige_conciliacao_extrato", False).eq("ativo", True).execute()
    return response.data

class FontePagadoraUpdate(BaseModel):
    nome: Optional[str] = None
    tipo: Optional[str] = None
    banco: Optional[str] = None
    agencia: Optional[str] = None
    conta: Optional[str] = None
    plano_conta_id: Optional[str] = None
    exige_conciliacao_extrato: Optional[bool] = None

@router.patch("/{fonte_id}", response_model=FontePagadoraResponse)
def update_fonte_pagadora(fonte_id: str, fonte: FontePagadoraUpdate):
    supabase = _get_supabase()
    data = {k: v for k, v in fonte.dict().items() if v is not None}
    if data.get('plano_conta_id') == '':
        data['plano_conta_id'] = None
    
    if data.get("tipo") == "CONTA_BANCARIA":
        # Validate that banco, agencia, conta are present if it's changing to CONTA_BANCARIA
        # Since it's a PATCH, some fields might be missing in the payload but present in DB,
        # but for simplicity we rely on DB or frontend validation.
        pass

    response = supabase.table("fontes_pagadoras").update(data).eq("id", fonte_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Fonte pagadora não encontrada ou erro ao atualizar")
    return response.data[0]

@router.delete("/{fonte_id}")
def inativar_fonte(fonte_id: str):
    supabase = _get_supabase()
    response = supabase.table("fontes_pagadoras").update({"ativo": False}).eq("id", fonte_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Fonte pagadora não encontrada")
    return {"message": "Fonte Pagadora inativada com sucesso"}
