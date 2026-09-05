"""
validacao_router.py
===================
Endpoints para a tela de validação de documentos fiscais.

GET  /api/v1/validacao/documentos          — lista documentos extraídos
GET  /api/v1/validacao/documentos/{id}     — detalhe + URL assinada da foto
PATCH /api/v1/validacao/documentos/{id}    — salva correções + confirma/rejeita
"""

import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from supabase import create_client

router = APIRouter(prefix="/api/v1/validacao", tags=["Validação"])


def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)


# ------------------------------------------------------------------ #
#  Schemas                                                            #
# ------------------------------------------------------------------ #

class DocumentoResumo(BaseModel):
    id: str
    filename: str
    condo_nome: str
    status: str
    fornecedor: str | None
    valor_total: float | None
    data_emissao: str | None
    numero_doc: str | None
    criado_em: str
    extraido_em: str | None


class DocumentoDetalhe(BaseModel):
    id: str
    filename: str
    condo_nome: str
    status: str
    foto_url: str | None          # URL assinada (1h) para exibir a foto
    fornecedor: str | None
    cnpj_cpf: str | None
    numero_doc: str | None
    data_emissao: str | None
    data_vencimento: str | None
    data_pagamento: str | None
    valor_total: float | None
    descricao: str | None
    hash_arquivo: str | None
    sugestao_contabil: dict | None
    criado_em: str
    extraido_em: str | None
    erro_msg: str | None


class ValidacaoPayload(BaseModel):
    acao: Literal["confirmar", "rejeitar"]
    # campos editáveis pela usuária
    fornecedor: str | None = None
    cnpj_cpf: str | None = None
    numero_doc: str | None = None
    data_emissao: str | None = None
    data_vencimento: str | None = None
    data_pagamento: str | None = None
    valor_total: float | None = None
    descricao: str | None = None


class ValidacaoResponse(BaseModel):
    ok: bool
    id: str
    status: str


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

@router.get("/documentos", response_model=list[DocumentoResumo])
async def listar_documentos(
    status: str = "extraido",   # filtro padrão: só os prontos pra validar
    limit: int = 50,
):
    """
    Lista documentos fiscais filtrados por status.
    Padrão: status=extraido (prontos para validação).
    Passar status=todos retorna todos os registros.
    """
    supabase = _get_supabase()

    query = (
        supabase.table("documentos_fiscais")
        .select("id, filename, condo_nome, status, fornecedor, valor_total, data_emissao, numero_doc, criado_em, extraido_em")
        .order("criado_em", desc=True)
        .limit(limit)
    )

    if status != "todos":
        query = query.eq("status", status)

    result = query.execute()
    return result.data or []


@router.get("/documentos/{documento_id}", response_model=DocumentoDetalhe)
async def detalhe_documento(documento_id: str):
    """
    Retorna todos os dados de um documento + URL assinada (1h) para
    exibir a foto diretamente no browser sem expor o bucket publicamente.
    """
    supabase = _get_supabase()

    result = (
        supabase.table("documentos_fiscais")
        .select("*")
        .eq("id", documento_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    doc = result.data

    # Gera URL assinada da foto (válida por 1 hora)
    foto_url = None
    try:
        bucket = doc.get("bucket", os.environ.get("SUPABASE_BUCKET_CONDOMINIOS", "integre"))
        signed = supabase.storage.from_(bucket).create_signed_url(
            doc["storage_path"], expires_in=3600
        )
        foto_url = signed.get("signedURL") or signed.get("signedUrl")
    except Exception:
        pass  # foto não disponível, mas não quebra o fluxo

    return DocumentoDetalhe(
        id=doc["id"],
        filename=doc["filename"],
        condo_nome=doc["condo_nome"],
        status=doc["status"],
        foto_url=foto_url,
        fornecedor=doc.get("fornecedor"),
        cnpj_cpf=doc.get("cnpj_cpf"),
        numero_doc=doc.get("numero_doc"),
        data_emissao=doc.get("data_emissao"),
        data_vencimento=doc.get("data_vencimento"),
        data_pagamento=doc.get("data_pagamento"),
        valor_total=doc.get("valor_total"),
        descricao=doc.get("descricao"),
        hash_arquivo=doc.get("hash_arquivo"),
        sugestao_contabil=doc.get("sugestao_contabil"),
        criado_em=doc["criado_em"],
        extraido_em=doc.get("extraido_em"),
        erro_msg=doc.get("erro_msg"),
    )


@router.patch("/documentos/{documento_id}", response_model=ValidacaoResponse)
async def validar_documento(documento_id: str, payload: ValidacaoPayload):
    """
    Confirma ou rejeita um documento após revisão da usuária.
    - confirmar: salva os dados corrigidos + status = "validado"
    - rejeitar:  marca status = "erro" (volta para revisão manual)
    """
    supabase = _get_supabase()

    # Verifica que o documento existe e está no estado certo
    result = (
        supabase.table("documentos_fiscais")
        .select("id, status")
        .eq("id", documento_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    doc = result.data
    if doc["status"] not in ("extraido", "erro"):
        raise HTTPException(
            status_code=400,
            detail=f"Documento com status '{doc['status']}' não pode ser validado.",
        )

    if payload.acao == "confirmar":
        update = {
            "status":          "validado",
            "fornecedor":      payload.fornecedor,
            "cnpj_cpf":        payload.cnpj_cpf,
            "numero_doc":      payload.numero_doc,
            "data_emissao":    payload.data_emissao,
            "data_vencimento": payload.data_vencimento,
            "data_pagamento":  payload.data_pagamento,
            "valor_total":     payload.valor_total,
            "descricao":       payload.descricao,
            "erro_msg":        None,
        }
        novo_status = "validado"
    else:
        update = {
            "status":   "erro",
            "erro_msg": "Rejeitado manualmente pela usuária.",
        }
        novo_status = "erro"

    supabase.table("documentos_fiscais").update(update).eq("id", documento_id).execute()

    return ValidacaoResponse(ok=True, id=documento_id, status=novo_status)
