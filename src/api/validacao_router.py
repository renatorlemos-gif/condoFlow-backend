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
    administradora_id: int | str | None
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
    conta_codigo: str | None = None


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
        administradora_id=doc.get("administradora_id"),
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
        .select("id, status, condominio_id, administradora_id")
        .eq("id", documento_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    doc = result.data
    if doc["status"] not in ("extraido", "erro", "validado"):
        raise HTTPException(
            status_code=400,
            detail=f"Documento com status '{doc['status']}' não pode ser validado.",
        )

    if payload.acao == "confirmar":
        if not payload.conta_codigo or not payload.conta_codigo.strip():
            raise HTTPException(
                status_code=400,
                detail="A conta contábil é obrigatória para validação."
            )
            
        admin_id = doc.get("administradora_id")
        if admin_id:
            conta_result = (
                supabase.table("plano_contas")
                .select("codigo")
                .eq("administradora_id", admin_id)
                .eq("codigo", payload.conta_codigo)
                .execute()
            )
            if not conta_result.data:
                raise HTTPException(
                    status_code=400,
                    detail="A conta contábil fornecida não pertence ao plano de contas atual."
                )

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

    if payload.acao == "confirmar" and payload.conta_codigo and payload.fornecedor:
        import re
        import asyncio
        fornec_norm = str(payload.fornecedor).strip().upper()
        fornec_norm = re.sub(r'\s+', ' ', fornec_norm)
        
        admin_id = doc.get("administradora_id")
        desc_doc = payload.descricao or ""
        conta_codigo = payload.conta_codigo
        
        if admin_id:
            # Dispara background task para o motor semântico
            asyncio.create_task(_executar_merge_semantico(
                admin_id=admin_id,
                fornecedor=fornec_norm,
                conta_codigo=conta_codigo,
                nova_descricao=desc_doc
            ))

    return ValidacaoResponse(ok=True, id=documento_id, status=novo_status)


async def _executar_merge_semantico(admin_id: int, fornecedor: str, conta_codigo: str, nova_descricao: str):
    import os
    import logging
    logger = logging.getLogger("merge_semantico")
    
    try:
        supabase = _get_supabase()
        
        # 1. Busca contexto existente
        res = supabase.table("plano_contas").select("contexto").eq("administradora_id", str(admin_id)).eq("codigo", conta_codigo).execute()
        
        contexto_existente = ""
        if res.data and res.data[0].get("contexto"):
            contexto_existente = res.data[0]["contexto"]
            
        # 2. Sintetiza novo contexto com Gemini
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        
        prompt = (
            f"Você é um motor semântico contábil. Faça o merge do contexto existente com a nova descrição da despesa.\n"
            f"Conta Contábil: {conta_codigo}\n"
            f"Contexto Existente: '{contexto_existente}'\n"
            f"Nova Descrição: '{nova_descricao}'\n\n"
            f"INSTRUÇÃO ESTRITA: Você DEVE abstrair e omitir quaisquer nomes de prestadores de serviço, empresas, pessoas, datas, meses e locais específicos presentes na Nova Descrição ou no Contexto Existente. "
            f"Gere um texto descritivo e conciso (máximo 300 caracteres) explicando de forma genérica, conceitual e abrangente a natureza das despesas desta regra.\n"
            f"Responda APENAS com o novo texto de contexto."
        )
        
        resp = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[prompt],
            config=types.GenerateContentConfig(temperature=0.0)
        )
        
        novo_contexto = resp.text.strip()
        if len(novo_contexto) > 300:
            novo_contexto = novo_contexto[:297] + "..."
            
        # 2.5 Gera novo embedding vetorial
        emb_res = client.models.embed_content(
            model="gemini-embedding-2",
            contents=novo_contexto,
            config=types.EmbedContentConfig(output_dimensionality=768)
        )
        novo_embedding = emb_res.embeddings[0].values
            
        # 3. Salva no Supabase via UPDATE na tabela plano_contas (já existe, apenas atualizamos o contexto e embedding)
        supabase.table("plano_contas").update({
            "contexto": novo_contexto,
            "embedding": list(novo_embedding),
            "criada_por_ia": True,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("administradora_id", str(admin_id)).eq("codigo", conta_codigo).execute()
        
        # 4. Efeito Cascata (Ripple Effect) em lote
        # Atualiza sugestão de conta de todos os documentos 'pendente' do mesmo fornecedor e admin
        docs_pendentes = supabase.table("documentos_fiscais").select("id, sugestao_contabil").eq("administradora_id", admin_id).eq("fornecedor", fornecedor).eq("status", "pendente").execute()
        
        if docs_pendentes.data:
            for d in docs_pendentes.data:
                sugestao = d.get("sugestao_contabil") or {}
                sugestao["conta_debito_codigo"] = conta_codigo
                sugestao["origem_sugestao"] = "ripple_effect_merge"
                
                supabase.table("documentos_fiscais").update({
                    "sugestao_contabil": sugestao
                }).eq("id", d["id"]).execute()
                
        logger.info(f"Merge semântico concluído para fornecedor {fornecedor}.")
        
    except Exception as e:
        logger.error(f"Erro no merge semântico: {e}")
