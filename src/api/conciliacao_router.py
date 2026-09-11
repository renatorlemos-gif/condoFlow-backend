"""
conciliacao_router.py
=====================
Endpoints para a tela de conciliação bancária.

GET  /api/v1/conciliacao/transacoes          — lista transações com sugestão de documento
POST /api/v1/conciliacao/conciliar           — confirma um par transação ↔ documento
DELETE /api/v1/conciliacao/{id}              — desfaz uma conciliação
GET  /api/v1/conciliacao/documentos-disponiveis — documentos validados ainda não conciliados
"""

import os
from datetime import datetime, timezone, timedelta
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
    score: float  # 0-1, confiança da sugestão


class TransacaoComSugestao(BaseModel):
    id: str
    data_transacao: str
    descricao: str | None
    valor: float
    tipo: str
    banco: str
    condo_nome: str
    conciliacao_id: str | None      # preenchido se já conciliada
    documento_id: str | None        # preenchido se já conciliada
    documento_fornecedor: str | None
    documento_valor: float | None
    status_conciliacao: Literal["conciliada", "sugerida", "pendente"]
    sugestao: DocumentoSugestao | None


class ConciliarPayload(BaseModel):
    transacao_id: str
    documento_id: str
    status: Literal["automatica", "manual"] = "manual"


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
    """
    Calcula score de 0-1 para o par transação ↔ documento.
    Critérios:
    - Valor igual: +0.6
    - Data da transação dentro de 30 dias da emissão: +0.3 (decai com distância)
    - Tipo débito (pagamento): +0.1
    """
    score = 0.0

    val_trans = float(transacao.get("valor") or 0)
    val_doc   = float(documento.get("valor_total") or 0)

    if val_trans > 0 and val_doc > 0:
        if abs(val_trans - val_doc) < 0.01:
            score += 0.6
        elif abs(val_trans - val_doc) / max(val_trans, val_doc) < 0.05:
            score += 0.3  # diferença menor que 5%

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
    """Retorna o melhor documento candidato com score >= 0.6, ou None."""
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
    mes_ano: str | None = None,   # formato: "2026-08"
    banco: str | None = None,
    apenas_pendentes: bool = True,
    limit: int = 100,
):
    """
    Lista transações do extrato com sugestão automática de documento.
    Filtra por mês/ano (ex: 2026-08) e banco opcionalmente.
    """
    supabase = _get_supabase()

    # Busca transações
    query = (
        supabase.table("transacoes_extrato")
        .select("*")
        .order("data_transacao", desc=True)
        .limit(limit)
    )
    if banco:
        query = query.eq("banco", banco)
    if mes_ano:
        inicio = f"{mes_ano}-01"
        ano, mes = mes_ano.split("-")
        ultimo_dia = 31
        fim = f"{mes_ano}-{ultimo_dia}"
        query = query.gte("data_transacao", inicio).lte("data_transacao", fim)

    transacoes = query.execute().data or []

    # Busca conciliações já existentes
    trans_ids = [t["id"] for t in transacoes]
    conciliacoes = {}
    if trans_ids:
        conc_result = (
            supabase.table("conciliacoes")
            .select("*, documentos_fiscais(fornecedor, valor_total)")
            .in_("transacao_id", trans_ids)
            .execute()
        )
        for c in (conc_result.data or []):
            conciliacoes[c["transacao_id"]] = c

    # Busca documentos disponíveis para sugestão (validados, não conciliados)
    docs_result = (
        supabase.table("documentos_fiscais")
        .select("id, fornecedor, numero_doc, data_emissao, valor_total")
        .eq("status", "validado")
        .execute()
    )
    docs_disponiveis = docs_result.data or []

    # IDs já conciliados (não podem ser sugeridos novamente)
    docs_ja_conciliados = {c.get("documento_id") for c in conciliacoes.values()}
    docs_livres = [d for d in docs_disponiveis if d["id"] not in docs_ja_conciliados]

    resultado = []
    for trans in transacoes:
        conc = conciliacoes.get(trans["id"])

        if conc:
            doc_info = conc.get("documentos_fiscais") or {}
            resultado.append(TransacaoComSugestao(
                **{k: trans[k] for k in ["id","data_transacao","descricao","valor","tipo","banco","condo_nome"]},
                conciliacao_id=conc["id"],
                documento_id=conc["documento_id"],
                documento_fornecedor=doc_info.get("fornecedor"),
                documento_valor=doc_info.get("valor_total"),
                status_conciliacao="conciliada",
                sugestao=None,
            ))
        else:
            if apenas_pendentes is False or True:  # sempre inclui por ora
                sugestao = _buscar_sugestao(trans, docs_livres)
                resultado.append(TransacaoComSugestao(
                    **{k: trans[k] for k in ["id","data_transacao","descricao","valor","tipo","banco","condo_nome"]},
                    conciliacao_id=None,
                    documento_id=None,
                    documento_fornecedor=None,
                    documento_valor=None,
                    status_conciliacao="sugerida" if sugestao else "pendente",
                    sugestao=sugestao,
                ))

    return resultado


@router.get("/documentos-disponiveis", response_model=list[DocumentoDisponivel])
async def documentos_disponiveis(q: str | None = None):
    """
    Lista documentos validados ainda não conciliados.
    Aceita filtro de texto livre (q) para busca por fornecedor/número.
    """
    supabase = _get_supabase()

    # IDs já conciliados
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
    """
    Registra a conciliação de uma transação com um documento fiscal.
    Atualiza o status do documento para "conciliado".
    """
    supabase = _get_supabase()

    # Verifica se já existe conciliação para essa transação
    existente = (
        supabase.table("conciliacoes")
        .select("id")
        .eq("transacao_id", payload.transacao_id)
        .execute()
    )
    if existente.data:
        raise HTTPException(
            status_code=400,
            detail="Esta transação já está conciliada. Desfaça a conciliação atual antes de criar uma nova.",
        )

    # Insere a conciliação
    result = supabase.table("conciliacoes").insert({
        "transacao_id":  payload.transacao_id,
        "documento_id":  payload.documento_id,
        "status":        payload.status,
        "conciliado_em": datetime.now(timezone.utc).isoformat(),
        "conciliado_por": "sistema" if payload.status == "automatica" else "usuaria",
    }).execute()

    conciliacao_id = result.data[0]["id"]

    # Atualiza status do documento para "conciliado"
    supabase.table("documentos_fiscais").update({
        "status": "conciliado"
    }).eq("id", payload.documento_id).execute()

    return ConciliarResponse(ok=True, conciliacao_id=conciliacao_id)


@router.delete("/{conciliacao_id}")
async def desfazer_conciliacao(conciliacao_id: str):
    """
    Desfaz uma conciliação: remove o registro e volta o documento
    para status "validado".
    """
    supabase = _get_supabase()

    conc = (
        supabase.table("conciliacoes")
        .select("documento_id")
        .eq("id", conciliacao_id)
        .single()
        .execute()
    )
    if not conc.data:
        raise HTTPException(status_code=404, detail="Conciliação não encontrada.")

    documento_id = conc.data["documento_id"]

    supabase.table("conciliacoes").delete().eq("id", conciliacao_id).execute()
    supabase.table("documentos_fiscais").update({"status": "validado"}).eq("id", documento_id).execute()

    return {"ok": True, "conciliacao_id": conciliacao_id}
