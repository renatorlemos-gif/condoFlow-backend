import os
import asyncio
from datetime import date, datetime, timezone
from typing import Optional
import pymupdf

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from pydantic import BaseModel, Field, field_validator
from supabase import create_client

from src.utils.despesa_parser import DespesaParser, DadosExtraidosDTO
from src.utils.supabase_storage import upload_despesa
from src.services.conhecimento_service import ConhecimentoService, SugestaoContabilDTO
from src.services.lote_service import LoteService, ItemLoteContabil

router = APIRouter(prefix="/api/v1/despesas", tags=["Despesas & Lote Contábil"])


def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)


# ------------------------------------------------------------------ #
#  Schemas                                                            #
# ------------------------------------------------------------------ #

class ProcessarDespesaResponse(BaseModel):
    hash_arquivo: str
    dados_extraidos: DadosExtraidosDTO
    sugestao_contabil: SugestaoContabilDTO


class UploadResponse(BaseModel):
    ok: bool
    despesa_id: str
    path: str
    signed_url: str
    bucket: str
    filename: str


class DespesaManualCreate(BaseModel):
    condominio_id: str = Field(..., description="UUID do condomínio ativo")
    administradora_id: str = Field(..., description="UUID ou ID da administradora do condomínio")
    data_pagamento: date = Field(..., description="Data efetiva do débito/pagamento (YYYY-MM-DD)")
    valor_total: float = Field(..., gt=0.0, description="Valor contábil da despesa em reais (deve ser > 0)")
    competencia: str = Field(..., description="Competência de referência no formato MM/YYYY ou YYYY-MM")
    conta_despesa_id: str = Field(..., description="UUID da conta devedora no plano de contas")
    fonte_pagadora_id: str = Field(..., description="UUID da fonte pagadora bancária (conta credora)")
    descricao: str = Field(..., min_length=1, max_length=255, description="Histórico descritivo contábil (ideal até 80 chars)")
    fornecedor: Optional[str] = Field(None, max_length=150, description="Nome do favorecido ou instituição bancária (opcional)")

    @field_validator("competencia")
    @classmethod
    def validar_formato_competencia(cls, v: str) -> str:
        v = v.strip()
        if "/" in v:
            partes = v.split("/")
            if len(partes) == 2 and ((len(partes[0]) == 2 and len(partes[1]) == 4) or (len(partes[0]) == 4 and len(partes[1]) == 2)):
                return v
        elif "-" in v:
            partes = v.split("-")
            if len(partes) == 2 and ((len(partes[0]) == 4 and len(partes[1]) == 2) or (len(partes[0]) == 2 and len(partes[1]) == 4)):
                return v
        raise ValueError("A competência deve estar no formato MM/YYYY ou YYYY-MM.")

    @field_validator("descricao")
    @classmethod
    def validar_descricao(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A descrição não pode ser vazia.")
        return v

    @field_validator("fornecedor")
    @classmethod
    def sanitizar_fornecedor(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            return v if v else None
        return None


class DespesaManualOut(BaseModel):
    id: str = Field(..., description="UUID da despesa criada no banco")
    condominio_id: str
    administradora_id: str
    status: str = Field("validado", description="Status contábil inicial")
    numero_doc: str = Field("S/DOC", description="Identificador padrão para despesa sem documento físico")
    fornecedor: Optional[str] = None
    descricao: str
    descricao_original: Optional[str] = None
    valor_total: float
    data_pagamento: str
    data_emissao: str
    competencia: str
    conta_despesa_id: str
    fonte_pagadora_id: str
    sem_comprovante: bool = True
    tipo_origem: str = "manual_extrato"
    storage_path: Optional[str] = None
    bucket: Optional[str] = None
    filename: str
    criado_em: str
    extraido_em: Optional[str] = None

    model_config = {"extra": "ignore"}


def _extrair_mes_ano_competencia(competencia: str) -> tuple[int, int, str]:
    comp_clean = competencia.strip()
    sep = "/" if "/" in comp_clean else "-"
    partes = comp_clean.split(sep)
    if len(partes[0]) == 4:
        ano = int(partes[0])
        mes = int(partes[1])
    else:
        mes = int(partes[0])
        ano = int(partes[1])
    comp_fmt = f"{mes:02d}/{ano:04d}"
    return mes, ano, comp_fmt


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

@router.post("/upload", response_model=UploadResponse)
async def upload_despesa_fiscal(
    administradora_id: str = Form(...),
    condominio_id: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """
    Recebe uma foto ou PDF de despesa fiscal:
    1. Salva no Supabase Storage (bucket integre / despesas/)
    2. Insere registro em despesas com status = "pendente"
    3. Retorna imediatamente — o worker processa a extração em background
    """
    files_data = []
    for f in files:
        conteudo = await f.read()
        files_data.append((conteudo, f.content_type))
        
    def _merge_files_sync(files_list):
        merged_pdf = pymupdf.open()
        for conteudo, content_type in files_list:
            if content_type == "application/pdf":
                pdf_doc = pymupdf.open("pdf", conteudo)
                merged_pdf.insert_pdf(pdf_doc)
            else:
                img_doc = pymupdf.open("img", conteudo)
                pdf_bytes = img_doc.convert_to_pdf()
                pdf_doc = pymupdf.open("pdf", pdf_bytes)
                merged_pdf.insert_pdf(pdf_doc)
        return merged_pdf.write(deflate=True, garbage=4)
    
    final_bytes = await asyncio.to_thread(_merge_files_sync, files_data)
    
    filename = f"doc_{int(datetime.now(timezone.utc).timestamp())}.pdf"
    mime_type = "application/pdf"

    # 1. Upload para o Supabase Storage
    try:
        resultado = await asyncio.to_thread(lambda: upload_despesa(
            file_bytes=final_bytes,
            filename=filename,
            mime_type=mime_type,
            prefixo=condominio_id,
        ))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar no Supabase Storage: {str(e)}")

    # 2. Insere registro no banco com status "pendente"
    try:
        def _insert_db():
            supabase = _get_supabase()
            return supabase.table("despesas").insert({
                "administradora_id": administradora_id,
                "condominio_id": condominio_id,
                "bucket":       resultado["bucket"],
                "storage_path": resultado["path"],
                "filename":     filename,
                "status":       "pendente",
                "criado_em":    datetime.now(timezone.utc).isoformat(),
            }).execute()

        insert = await asyncio.to_thread(_insert_db)

        despesa_id = insert.data[0]["id"]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao registrar no banco: {str(e)}")

    return UploadResponse(
        ok=True,
        despesa_id=despesa_id,
        path=resultado["path"],
        signed_url=resultado["signed_url"],
        bucket=resultado["bucket"],
        filename=filename,
    )


@router.post("/escanear", response_model=ProcessarDespesaResponse)
async def escanear_despesa(
    condominio_id: str,
    file: UploadFile = File(...),
    parser: DespesaParser = Depends(),
    conhecimento_service: ConhecimentoService = Depends(),
):
    """
    Extrai dados de um despesa fiscal via Gemini e retorna
    a sugestão contábil. Usado pelo fluxo de desktop (validação imediata).
    """
    if file.content_type not in ["application/pdf", "image/jpeg", "image/png"]:
        raise HTTPException(
            status_code=400,
            detail="Formato não suportado. Envie PDF, JPG ou PNG.",
        )

    dados_extraidos, hash_arquivo = await parser.parse_despesa(file)
    sugestao = await conhecimento_service.gerar_sugestao(dados_extraidos, condominio_id)

    return ProcessarDespesaResponse(
        hash_arquivo=hash_arquivo,
        dados_extraidos=dados_extraidos,
        sugestao_contabil=sugestao,
    )


@router.post("/lote/adicionar", response_model=ItemLoteContabil)
async def adicionar_ao_lote(
    item: ItemLoteContabil,
    lote_service: LoteService = Depends(),
):
    """Salva o item validado/ajustado pelo usuário no lote contábil."""
    return item


@router.post("/{doc_id}/reprocessar")
async def reprocessar_despesa(doc_id: str):
    """Reprocessa um despesa enviando-o de volta para a fila de extração OCR."""
    try:
        supabase = _get_supabase()
        supabase.table("despesas").update({
            "status": "pendente",
            "erro_msg": None
        }).eq("id", doc_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao reprocessar: {str(e)}")


@router.post("/manual", response_model=DespesaManualOut, status_code=201)
async def criar_despesa_manual(payload: DespesaManualCreate):
    """
    Registra uma despesa contábil manual sem documento físico (S/DOC),
    inserindo diretamente no status 'validado' para conciliação imediata.
    """
    # 1. Validação temporal de competência (HTTP 422)
    comp_mes, comp_ano, comp_fmt = _extrair_mes_ano_competencia(payload.competencia)
    data_pag = payload.data_pagamento
    if data_pag.year != comp_ano or data_pag.month != comp_mes:
        data_pag_fmt = f"{data_pag.day:02d}/{data_pag.month:02d}/{data_pag.year:04d}"
        raise HTTPException(
            status_code=422,
            detail=f"A data de pagamento ({data_pag_fmt}) está fora do período em processamento ({comp_fmt}). Ajuste a data para este mês ou altere a competência."
        )

    supabase = _get_supabase()

    # 2. Validação referencial do plano_contas (HTTP 404)
    conta_res = (
        supabase.table("plano_contas")
        .select("id, administradora_id")
        .eq("id", payload.conta_despesa_id)
        .execute()
    )
    if not conta_res.data or str(conta_res.data[0].get("administradora_id")) != str(payload.administradora_id):
        raise HTTPException(
            status_code=404,
            detail="Conta contábil de despesa não encontrada para a administradora."
        )

    # 3. Validação referencial de fontes_pagadoras (HTTP 404)
    fonte_res = (
        supabase.table("fontes_pagadoras")
        .select("id, condominio_id")
        .eq("id", payload.fonte_pagadora_id)
        .execute()
    )
    if not fonte_res.data or str(fonte_res.data[0].get("condominio_id")) != str(payload.condominio_id):
        raise HTTPException(
            status_code=404,
            detail="Fonte pagadora não encontrada para o condomínio."
        )

    # 4. Inserção determinística na tabela despesas
    agora = datetime.now(timezone.utc)
    agora_iso = agora.isoformat()
    ts = int(agora.timestamp())
    filename = f"manual_{ts}.pdf"
    data_pag_iso = data_pag.isoformat()

    registro_despesa = {
        "condominio_id": payload.condominio_id,
        "administradora_id": payload.administradora_id,
        "data_pagamento": data_pag_iso,
        "data_emissao": data_pag_iso,
        "valor_total": payload.valor_total,
        "competencia": payload.competencia,
        "conta_despesa_id": payload.conta_despesa_id,
        "fonte_pagadora_id": payload.fonte_pagadora_id,
        "descricao": payload.descricao,
        "descricao_original": payload.descricao,
        "fornecedor": payload.fornecedor,
        "status": "validado",
        "numero_doc": "S/DOC",
        "sem_comprovante": True,
        "tipo_origem": "manual_extrato",
        "storage_path": None,
        "bucket": None,
        "filename": filename,
        "criado_em": agora_iso,
        "extraido_em": agora_iso,
    }

    try:
        insert_res = supabase.table("despesas").insert(registro_despesa).execute()
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Erro ao persistir despesa manual no banco de dados.")
        nova_despesa = insert_res.data[0]
        if "administradora_id" in nova_despesa and nova_despesa["administradora_id"] is not None:
            nova_despesa["administradora_id"] = str(nova_despesa["administradora_id"])
        return DespesaManualOut(**nova_despesa)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao registrar despesa manual: {str(e)}")
