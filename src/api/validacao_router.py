"""
validacao_router.py
===================
Endpoints para a tela de validação de despesas fiscais.

GET  /api/v1/validacao/despesas          — lista despesas extraídos
GET  /api/v1/validacao/despesas/{id}     — detalhe + URL assinada da foto
PATCH /api/v1/validacao/despesas/{id}    — salva correções + confirma/rejeita
"""

import os
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
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

class DespesaResumo(BaseModel):
    id: str
    filename: str
    status: str
    fornecedor: str | None
    valor_total: float | None
    data_emissao: str | None
    numero_doc: str | None
    criado_em: str
    extraido_em: str | None
    competencia: str | None = None
    conta_devedora_codigo: str | None = None
    conta_devedora_descricao: str | None = None
    fonte_pagadora_id: str | None = None
    conta_credora_descricao: str | None = None

class DespesaDetalhe(BaseModel):
    id: str
    filename: str
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
    condominio_id: str | None
    chave_acesso: str | None
    competencia: str | None = None
    criado_em: str
    extraido_em: str | None
    erro_msg: str | None


class ValidacaoPayload(BaseModel):
    acao: Literal["confirmar", "rejeitar", "cancelar"]
    # campos editáveis pela usuária
    fornecedor: str | None = None
    cnpj_cpf: str | None = None
    numero_doc: str | None = None
    data_emissao: str | None = None
    data_vencimento: str | None = None
    data_pagamento: str | None = None
    valor_total: float | None = None
    descricao: str | None = None
    chave_acesso: str | None = None
    competencia: str | None = None
    fonte_pagadora_id: str | None = None
    conta_despesa_id: Optional[str] = None

class ValidacaoResponse(BaseModel):
    ok: bool
    id: str
    status: str


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

@router.get("/despesas", response_model=list[dict])
async def listar_despesas(
    status: str = "extraido",   # filtro padrão: só os prontos pra validar
    limit: int = 500,
):
    """
    Lista despesas fiscais filtrados por status.
    Padrão: status=extraido (prontos para validação).
    Passar status=todos retorna todos os registros.
    """
    supabase = _get_supabase()

    query = (
        supabase.table("despesas")
        .select("id, filename, administradora_id, condominio_id, status, fornecedor, valor_total, data_emissao, data_pagamento, numero_doc, criado_em, extraido_em, competencia, fonte_pagadora_id, plano_contas!conta_despesa_id(codigo_contabil, descricao)")
        .order("criado_em", desc=True)
        .limit(limit)
    )

    if status != "todos":
        if "," in status:
            statuses = [s.strip() for s in status.split(",")]
            query = query.in_("status", statuses)
        else:
            query = query.eq("status", status)

    result = query.execute()
    docs = result.data or []

    # Get unique administradora_ids to fetch plano_contas descriptions
    admin_ids = list(set([d.get("administradora_id") for d in docs if d.get("administradora_id")]))
    plano_contas_map = {}
    if admin_ids:
        pc_result = supabase.table("plano_contas").select("administradora_id, codigo_contabil, descricao").in_("administradora_id", admin_ids).execute()
        for pc in (pc_result.data or []):
            plano_contas_map[(pc["administradora_id"], pc["codigo_contabil"])] = pc["descricao"]
    
    # Map fontes_pagadoras
    fontes_ids = list(set([d.get("fonte_pagadora_id") for d in docs if d.get("fonte_pagadora_id")]))
    fontes_map = {}
    if fontes_ids:
        fontes_result = supabase.table("fontes_pagadoras").select("id, nome, plano_contas(codigo_contabil, descricao)").in_("id", fontes_ids).execute()
        for f in (fontes_result.data or []):
            pc = f.get("plano_contas") or {}
            cod = pc.get("codigo_contabil")
            desc = pc.get("descricao")
            if cod and desc:
                fontes_map[f["id"]] = f"{cod} - {desc}"
            elif cod:
                fontes_map[f["id"]] = cod
            else:
                fontes_map[f["id"]] = f["nome"]
            
    for d in docs:
        c_dev = d.get("plano_contas") or {}
        d["conta_devedora_codigo"] = c_dev.get("codigo_contabil")
        d["conta_devedora_descricao"] = c_dev.get("descricao")
        d.pop("plano_contas", None)
        
        # map conta_credora (which uses fonte_pagadora_id)
        f_id = d.get("fonte_pagadora_id")
        d["conta_codigo"] = None
        d["conta_credora_descricao"] = fontes_map.get(f_id) if f_id else None

    return docs


@router.get("/despesas/{despesa_id}", response_model=DespesaDetalhe)
async def detalhe_despesa(despesa_id: str):
    """
    Retorna todos os dados de um despesa + URL assinada (1h) para
    exibir a foto diretamente no browser sem expor o bucket publicamente.
    """
    supabase = _get_supabase()

    result = (
        supabase.table("despesas")
        .select("*")
        .eq("id", despesa_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Despesa não encontrado.")

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

    return DespesaDetalhe(
        id=doc["id"],
        filename=doc["filename"],
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
        condominio_id=doc.get("condominio_id"),
        chave_acesso=doc.get("chave_acesso"),
        competencia=doc.get("competencia"),
        criado_em=doc["criado_em"],
        extraido_em=doc.get("extraido_em"),
        erro_msg=doc.get("erro_msg"),
    )


class ContaOpcao(BaseModel):
    id: str
    codigo_contabil: str
    descricao: str
    similarity: float | None = None


@router.get("/despesas/{despesa_id}/contas-sugeridas", response_model=list[ContaOpcao])
async def obter_contas_sugeridas(despesa_id: str):
    """
    Retorna o plano de contas da administradora ordenado por similaridade
    com o embedding da despesa atual via RPC.
    """
    supabase = _get_supabase()

    result = (
        supabase.table("despesas")
        .select("administradora_id, embedding")
        .eq("id", despesa_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Despesa não encontrada.")

    doc = result.data
    admin_id = doc.get("administradora_id")
    embedding = doc.get("embedding")

    if not admin_id:
        return []

    top_5 = []
    top_5_ids = set()

    if embedding:
        import json
        try:
            q_emb = embedding if isinstance(embedding, list) else json.loads(embedding)
            res_rpc = supabase.rpc("match_plano_contas", {
                "query_embedding": q_emb,
                "match_threshold": -1.0,
                "match_count": 5,
                "p_administradora_id": str(admin_id)
            }).execute()
            
            if res_rpc.data:
                for row in res_rpc.data:
                    top_5.append(ContaOpcao(
                        id=row["id"],
                        codigo_contabil=row["codigo_contabil"],
                        descricao=row["descricao"],
                        similarity=row.get("similarity")
                    ))
                    top_5_ids.add(row["id"])
        except Exception as e:
            import logging
            logger = logging.getLogger("validacao_router")
            logger.error(f"Erro ao chamar match_plano_contas RPC: {e}")

    # Busca as outras contas
    res_contas = (
        supabase.table("plano_contas")
        .select("id, codigo_contabil, descricao")
        .eq("administradora_id", str(admin_id))
        .execute()
    )

    outras_contas = []
    if res_contas.data:
        for c in res_contas.data:
            if c["id"] not in top_5_ids:
                outras_contas.append({
                    "id": c["id"],
                    "codigo_contabil": c["codigo_contabil"],
                    "descricao": c["descricao"]
                })
        
        # Order alphabetically
        outras_contas.sort(key=lambda x: x["codigo_contabil"] or "")

        for c in outras_contas:
            top_5.append(ContaOpcao(
                id=c["id"],
                codigo_contabil=c["codigo_contabil"],
                descricao=c["descricao"],
                similarity=None
            ))

    return top_5


@router.patch("/despesas/{despesa_id}", response_model=ValidacaoResponse)
async def validar_despesa(despesa_id: str, payload: ValidacaoPayload, background_tasks: BackgroundTasks):
    import traceback
    try:
        return await _validar_despesa_impl(despesa_id, payload, background_tasks)
    except Exception as e:
        with open('FATAL_ERR.txt', 'w') as f:
            f.write(traceback.format_exc())
        raise

async def _validar_despesa_impl(despesa_id: str, payload: ValidacaoPayload, background_tasks: BackgroundTasks):
    supabase = _get_supabase()

    # Verifica que o despesa existe e está no estado certo
    result = (
        supabase.table("despesas")
        .select("id, status, condominio_id, administradora_id")
        .eq("id", despesa_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Despesa não encontrado.")

    doc = result.data
    if doc["status"] not in ("extraido", "erro", "validado"):
        raise HTTPException(
            status_code=400,
            detail=f"Despesa com status '{doc['status']}' não pode ser validado.",
        )

    if payload.acao == "cancelar":
        update = {
            "status": "extraido",
            "erro_msg": None,
            "conta_despesa_id": None
        }
        try:
            supabase.table("despesas").update(update).eq("id", despesa_id).execute()
        except Exception as e:
            import traceback
            raise HTTPException(status_code=500, detail=str(e) + " | " + traceback.format_exc())
        return ValidacaoResponse(ok=True, id=despesa_id, status="extraido")

    if payload.acao == "confirmar":
        if not payload.conta_despesa_id or not payload.conta_despesa_id.strip():
            raise HTTPException(
                status_code=400,
                detail="A conta contábil é obrigatória para validação."
            )
            
        if not payload.fonte_pagadora_id or not payload.fonte_pagadora_id.strip():
            raise HTTPException(
                status_code=400,
                detail="A fonte pagadora (Conta Crédito) é obrigatória para validação."
            )
            
        admin_id = doc.get("administradora_id")
        if admin_id:
            conta_result = (
                supabase.table("plano_contas").select("id").eq("id", payload.conta_despesa_id).eq("administradora_id", admin_id)
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
            "chave_acesso":    payload.chave_acesso,
            "competencia":     payload.competencia,
            "erro_msg":        None,
        }
        if payload.conta_despesa_id:
            update["conta_despesa_id"] = payload.conta_despesa_id
        if payload.fonte_pagadora_id:
            update["fonte_pagadora_id"] = payload.fonte_pagadora_id
        novo_status = "validado"
    else:
        update = {
            "status":   "erro",
            "erro_msg": "Rejeitado manualmente pela usuária.",
        }
        novo_status = "erro"

    try:
        supabase.table("despesas").update(update).eq("id", despesa_id).execute()
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=str(e) + " | " + traceback.format_exc())

    if payload.acao == "confirmar" and payload.conta_despesa_id:
        admin_id = doc.get("administradora_id")
        desc_doc = payload.descricao or ""
        conta_despesa_id = payload.conta_despesa_id
        
        if admin_id and desc_doc:
            # Dispara background task para o aprendizado contínuo
            background_tasks.add_task(
                _aprender_com_validacao,
                admin_id=admin_id,
                conta_despesa_id=conta_despesa_id,
                contexto_despesa=desc_doc
            )

    return ValidacaoResponse(ok=True, id=despesa_id, status=novo_status)


def _aprender_com_validacao(admin_id: int | str, conta_despesa_id: str, contexto_despesa: str):
    import logging
    from src.services.contexto_service import ContextoService
    logger = logging.getLogger("aprender_com_validacao")
    
    try:
        supabase = _get_supabase()
        
        # conta_despesa_id the primary key (UUID). We need the actual codigo_contabil.
        res = supabase.table("plano_contas").select("codigo_contabil, descricao").eq("id", conta_despesa_id).execute()
        if not res.data:
            logger.warning(f"Conta {conta_despesa_id} no encontrada para aprendizado.")
            return
            
        codigo_contabil = res.data[0]["codigo_contabil"]
        descricao = res.data[0]["descricao"]
        
        ContextoService.atualizar_contexto(supabase, str(admin_id), codigo_contabil, contexto_despesa, descricao)
    except Exception as e:
        logger.error(f"Erro no aprendizado contínuo: {e}")


class ScanQrResponse(BaseModel):
    sucesso: bool
    url: str | None = None
    mensagem: str | None = None


@router.post("/despesas/{despesa_id}/scan-qr", response_model=ScanQrResponse)
async def scan_qr_code(despesa_id: str):
    """
    Baixa o arquivo do Supabase, procura por QR Codes e retorna a URL se achar.
    """
    import asyncio
    supabase = _get_supabase()

    result = (
        supabase.table("despesas")
        .select("id, storage_path, bucket")
        .eq("id", despesa_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Despesa não encontrado.")

    doc = result.data
    storage_path = doc["storage_path"]
    bucket = doc.get("bucket", os.environ.get("SUPABASE_BUCKET_CONDOMINIOS", "integre"))

    # Baixa o arquivo do Supabase Storage
    try:
        file_bytes = await asyncio.to_thread(
            supabase.storage.from_(bucket).download,
            storage_path
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao baixar arquivo: {e}")

    ext = storage_path.rsplit(".", 1)[-1].lower()
    
    try:
        import fitz
        from pyzbar.pyzbar import decode
        from PIL import Image, ImageEnhance
        import io
        
        urls_encontradas = []

        if ext == "pdf":
            doc_pdf = fitz.open(stream=file_bytes, filetype="pdf")
            for page_num in range(len(doc_pdf)):
                page = doc_pdf.load_page(page_num)
                zoom = 2.5
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                img = img.convert('L')
                img = ImageEnhance.Contrast(img).enhance(2.0)
                img = img.point(lambda p: 255 if p > 128 else 0)
                
                decoded_objects = decode(img)
                for obj in decoded_objects:
                    url = obj.data.decode('utf-8')
                    if url.startswith("http"):
                        urls_encontradas.append(url)
                
                if urls_encontradas:
                    break
            
            doc_pdf.close()
        else:
            img = Image.open(io.BytesIO(file_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img = img.convert('L')
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = img.point(lambda p: 255 if p > 128 else 0)
            
            decoded_objects = decode(img)
            for obj in decoded_objects:
                url = obj.data.decode('utf-8')
                if url.startswith("http"):
                    urls_encontradas.append(url)

        if urls_encontradas:
            return ScanQrResponse(sucesso=True, url=urls_encontradas[0])
        else:
            return ScanQrResponse(sucesso=False, mensagem="Nenhum QR Code legível encontrado no despesa.")
            
    except ImportError:
        return ScanQrResponse(sucesso=False, mensagem="Bibliotecas de processamento (pyzbar/pymupdf) não estão instaladas no servidor.")
    except Exception as e:
        import logging
        logging.getLogger("validacao_router").error(f"Erro ao escanear QR Code: {e}")
        return ScanQrResponse(sucesso=False, mensagem=f"Erro ao processar imagem: {e}")


















