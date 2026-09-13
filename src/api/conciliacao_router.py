"""
conciliacao_router.py
=====================
Endpoints para a tela de conciliação bancária.

GET  /api/v1/conciliacao/transacoes          — lista transações com sugestão de documento
POST /api/v1/conciliacao/conciliar           — confirma pares transação ↔ documento (suporta N x N)
DELETE /api/v1/conciliacao/{id}              — desfaz uma conciliação (estorna lotes inteiros se agrupada)
GET  /api/v1/conciliacao/documentos-disponiveis — documentos validados ainda não conciliados
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from supabase import create_client

router = APIRouter(prefix="/api/v1/conciliacao", tags=["Conciliação"])


def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)


# ------------------------------------------------------------------ #
#  Schemas                                                            #
# ------------------------------------------------------------------ #

class DocumentoSugestao(BaseModel):
    id: str
    fornecedor: str | None
    numero_doc: str | None
    data_emissao: str | None
    valor_total: float | None
    score: float


class DocumentoConciliadoInfo(BaseModel):
    id: str
    fornecedor: str | None
    valor: float | None
    conciliacao_id: str


class TransacaoComSugestao(BaseModel):
    id: str
    data_transacao: str
    descricao: str | None = None
    valor: float
    tipo: str
    banco: str
    condo_nome: str
    
    documentos_conciliados: list[DocumentoConciliadoInfo] = []
    status_conciliacao: Literal["conciliada", "conciliada_em_lote", "sugerida", "pendente"]
    sugestao: DocumentoSugestao | None = None
    lote_id: str | None = None


class ConciliarPayload(BaseModel):
    transacoes_ids: list[str]
    documentos_ids: list[str]
    status: Literal["automatica", "manual", "lote"] = "manual"


class ConciliarResponse(BaseModel):
    ok: bool
    conciliacao_id: str


class DocumentoDisponivel(BaseModel):
    id: str
    fornecedor: str | None
    numero_doc: str | None
    data_emissao: str | None
    valor_total: float | None
    descricao: str | None


# ------------------------------------------------------------------ #
#  Lógica de sugestão automática                                      #
# ------------------------------------------------------------------ #

def _calcular_score(transacao: dict, documento: dict) -> float:
    score = 0.0
    val_trans = float(transacao.get("valor") or 0)
    val_doc   = float(documento.get("valor_total") or 0)

    if val_trans > 0 and val_doc > 0:
        if abs(val_trans - val_doc) < 0.01:
            score += 0.6
        elif abs(val_trans - val_doc) / max(val_trans, val_doc) < 0.05:
            score += 0.3

    data_trans_str = transacao.get("data_transacao")
    data_doc_str   = documento.get("data_emissao")
    if data_trans_str and data_doc_str:
        try:
            dt = datetime.fromisoformat(data_trans_str[:10])
            dd = datetime.fromisoformat(data_doc_str[:10])
            diff = abs((dt - dd).days)
            if diff <= 5:
                score += 0.3
            elif diff <= 15:
                score += 0.2
            elif diff <= 30:
                score += 0.1
        except Exception:
            pass

    if transacao.get("tipo") == "debito":
        score += 0.1

    return round(min(score, 1.0), 2)


def _buscar_sugestao(transacao: dict, documentos: list[dict]) -> DocumentoSugestao | None:
    melhor = None
    melhor_score = 0.0

    for doc in documentos:
        score = _calcular_score(transacao, doc)
        if score > melhor_score:
            melhor_score = score
            melhor = doc

    if melhor and melhor_score >= 0.6:
        return DocumentoSugestao(
            id=melhor["id"],
            fornecedor=melhor.get("fornecedor"),
            numero_doc=melhor.get("numero_doc"),
            data_emissao=melhor.get("data_emissao"),
            valor_total=melhor.get("valor_total"),
            score=melhor_score,
        )
    return None


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

@router.get("/transacoes", response_model=list[TransacaoComSugestao])
async def listar_transacoes(
    mes_ano: str | None = None,
    banco: str | None = None,
    apenas_pendentes: bool = True,
    limit: int = 100,
):
    supabase = _get_supabase()

    query = supabase.table("transacoes_extrato").select("*").order("data_transacao", desc=True).limit(limit)
    if banco:
        query = query.eq("banco", banco)
    if mes_ano:
        import calendar
        inicio = f"{mes_ano}-01"
        ano, mes = map(int, mes_ano.split("-"))
        _, ultimo_dia = calendar.monthrange(ano, mes)
        fim = f"{mes_ano}-{ultimo_dia:02d}"
        query = query.gte("data_transacao", inicio).lte("data_transacao", fim)

    transacoes = query.execute().data or []
    trans_ids = [t["id"] for t in transacoes]

    conciliacoes_por_trans = {}
    if trans_ids:
        conc_result = (
            supabase.table("conciliacoes")
            .select("*, documentos_fiscais(fornecedor, valor_total)")
            .in_("transacao_id", trans_ids)
            .execute()
        )
        for c in (conc_result.data or []):
            tid = c["transacao_id"]
            if tid not in conciliacoes_por_trans:
                conciliacoes_por_trans[tid] = []
            conciliacoes_por_trans[tid].append(c)

    docs_result = (
        supabase.table("documentos_fiscais")
        .select("id, fornecedor, numero_doc, data_emissao, valor_total")
        .eq("status", "validado")
        .execute()
    )
    docs_disponiveis = docs_result.data or []

    # Get already conciliados docs to remove from suggestions
    all_conc = supabase.table("conciliacoes").select("documento_id").execute().data or []
    docs_ja_conciliados = {c.get("documento_id") for c in all_conc}
    docs_livres = [d for d in docs_disponiveis if d["id"] not in docs_ja_conciliados]

    resultado = []
    for trans in transacoes:
        concs = conciliacoes_por_trans.get(trans["id"], [])
        
        if concs:
            docs_info = []
            lote_id = None
            is_lote = False
            for c in concs:
                doc_data = c.get("documentos_fiscais") or {}
                docs_info.append(DocumentoConciliadoInfo(
                    id=c["documento_id"],
                    fornecedor=doc_data.get("fornecedor"),
                    valor=doc_data.get("valor_total"),
                    conciliacao_id=c["id"]
                ))
                if str(c.get("status", "")).startswith("lote_"):
                    is_lote = True
                    lote_id = c["status"]

            # If there's multiple conciliations for this transaction, it's also a lote
            if len(concs) > 1:
                is_lote = True
                
            resultado.append(TransacaoComSugestao(
                **{k: trans.get(k) for k in ["id","data_transacao","descricao","valor","tipo","banco","condo_nome"]},
                documentos_conciliados=docs_info,
                status_conciliacao="conciliada_em_lote" if is_lote else "conciliada",
                sugestao=None,
                lote_id=lote_id if is_lote else None,
            ))
        else:
            sugestao = _buscar_sugestao(trans, docs_livres)
            resultado.append(TransacaoComSugestao(
                **{k: trans.get(k) for k in ["id","data_transacao","descricao","valor","tipo","banco","condo_nome"]},
                documentos_conciliados=[],
                status_conciliacao="sugerida" if sugestao else "pendente",
                sugestao=sugestao,
                lote_id=None,
            ))

    return resultado


@router.get("/documentos-disponiveis", response_model=list[DocumentoDisponivel])
async def documentos_disponiveis(q: str | None = None):
    supabase = _get_supabase()

    conc = supabase.table("conciliacoes").select("documento_id").execute()
    ids_conciliados = {c["documento_id"] for c in (conc.data or [])}

    docs = (
        supabase.table("documentos_fiscais")
        .select("id, fornecedor, numero_doc, data_emissao, valor_total, descricao")
        .eq("status", "validado")
        .order("data_emissao", desc=True)
        .limit(200)
        .execute()
        .data or []
    )
    docs = [d for d in docs if d["id"] not in ids_conciliados]

    if q:
        q_lower = q.lower()
        docs = [
            d for d in docs
            if q_lower in (d.get("fornecedor") or "").lower()
            or q_lower in (d.get("numero_doc") or "").lower()
        ]

    return docs


@router.post("/conciliar", response_model=ConciliarResponse)
async def conciliar(payload: ConciliarPayload):
    supabase = _get_supabase()

    if not payload.transacoes_ids or not payload.documentos_ids:
        raise HTTPException(status_code=400, detail="É necessário ao menos uma transação e um documento.")

    # Verifica se alguma transação já está conciliada
    existentes = (
        supabase.table("conciliacoes")
        .select("id")
        .in_("transacao_id", payload.transacoes_ids)
        .execute()
    )
    if existentes.data:
        raise HTTPException(
            status_code=400,
            detail="Uma ou mais transações selecionadas já estão conciliadas."
        )

    # Verifica se algum documento já está conciliado
    docs_existentes = (
        supabase.table("conciliacoes")
        .select("id")
        .in_("documento_id", payload.documentos_ids)
        .execute()
    )
    if docs_existentes.data:
        raise HTTPException(
            status_code=400,
            detail="Um ou mais documentos selecionados já estão conciliados."
        )

    # Busca valores para validar Delta Zero
    trans_data = supabase.table("transacoes_extrato").select("valor").in_("id", payload.transacoes_ids).execute().data or []
    docs_data = supabase.table("documentos_fiscais").select("valor_total").in_("id", payload.documentos_ids).execute().data or []

    total_trans = sum(float(t.get("valor") or 0) for t in trans_data)
    total_docs = sum(float(d.get("valor_total") or 0) for d in docs_data)

    diferenca = abs(total_trans - total_docs)
    
    # Tolerância de R$ 0,05 para divergências de centavos (RNF-03)
    if diferenca > 0.05:
        raise HTTPException(
            status_code=400, 
            detail=f"Diferença contábil de R$ {diferenca:.2f} excede a tolerância. A soma de transações deve ser igual aos documentos."
        )

    # Criação do Lote / Associação N x N
    is_lote = len(payload.transacoes_ids) > 1 or len(payload.documentos_ids) > 1
    lote_id = f"lote_{uuid.uuid4().hex[:8]}"
    status_str = lote_id if is_lote else payload.status

    inserts = []
    for t_id in payload.transacoes_ids:
        for d_id in payload.documentos_ids:
            inserts.append({
                "transacao_id": t_id,
                "documento_id": d_id,
                "status": status_str,
                "conciliado_em": datetime.now(timezone.utc).isoformat(),
                "conciliado_por": "sistema" if payload.status == "automatica" else "usuaria",
            })

    result = supabase.table("conciliacoes").insert(inserts).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Erro ao inserir conciliação.")

    conciliacao_id_ref = result.data[0]["id"]

    # Atualiza documentos
    supabase.table("documentos_fiscais").update({"status": "conciliado"}).in_("id", payload.documentos_ids).execute()

    return ConciliarResponse(ok=True, conciliacao_id=lote_id if is_lote else conciliacao_id_ref)


@router.delete("/{conciliacao_id}")
async def desfazer_conciliacao(conciliacao_id: str):
    supabase = _get_supabase()

    # Verifica se está passando um ID de lote (prefixado com lote_)
    if conciliacao_id.startswith("lote_"):
        # Desfaz todo o lote
        conc_lote = supabase.table("conciliacoes").select("documento_id").eq("status", conciliacao_id).execute().data or []
        if not conc_lote:
            raise HTTPException(status_code=404, detail="Lote de conciliação não encontrado.")
            
        doc_ids = list({c["documento_id"] for c in conc_lote})
        
        supabase.table("conciliacoes").delete().eq("status", conciliacao_id).execute()
        supabase.table("documentos_fiscais").update({"status": "validado"}).in_("id", doc_ids).execute()
        return {"ok": True, "lote_desfeito": True}

    # Desfaz conciliação individual
    conc = supabase.table("conciliacoes").select("documento_id, status, transacao_id").eq("id", conciliacao_id).execute()
    if not conc.data:
        raise HTTPException(status_code=404, detail="Conciliação não encontrada.")

    registro = conc.data[0]
    
    # Se na verdade era parte de um lote via ID direto, vamos estornar o lote todo para evitar inconsistências
    if str(registro.get("status", "")).startswith("lote_"):
        lote_str = registro["status"]
        conc_lote = supabase.table("conciliacoes").select("documento_id").eq("status", lote_str).execute().data or []
        doc_ids = list({c["documento_id"] for c in conc_lote})
        supabase.table("conciliacoes").delete().eq("status", lote_str).execute()
        supabase.table("documentos_fiscais").update({"status": "validado"}).in_("id", doc_ids).execute()
        return {"ok": True, "lote_desfeito": True, "obs": "A conciliação fazia parte de um lote, que foi totalmente desfeito."}

    # Estorno normal 1x1
    documento_id = registro["documento_id"]
    supabase.table("conciliacoes").delete().eq("id", conciliacao_id).execute()
    supabase.table("documentos_fiscais").update({"status": "validado"}).eq("id", documento_id).execute()

    return {"ok": True, "conciliacao_id": conciliacao_id}
