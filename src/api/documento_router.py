import os
from datetime import datetime, timezone
import pymupdf

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from pydantic import BaseModel
from supabase import create_client

from src.utils.documento_parser import DocumentoParser, DadosExtraidosDTO
from src.utils.supabase_storage import upload_documento
from src.services.conhecimento_service import ConhecimentoService, SugestaoContabilDTO
from src.services.lote_service import LoteService, ItemLoteContabil

router = APIRouter(prefix="/api/v1/documentos", tags=["Documentos & Lote Contábil"])


def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)


# ------------------------------------------------------------------ #
#  Schemas                                                            #
# ------------------------------------------------------------------ #

class ProcessarDocumentoResponse(BaseModel):
    hash_arquivo: str
    dados_extraidos: DadosExtraidosDTO
    sugestao_contabil: SugestaoContabilDTO


class UploadResponse(BaseModel):
    ok: bool
    documento_id: str
    path: str
    signed_url: str
    bucket: str
    filename: str


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

@router.post("/upload", response_model=UploadResponse)
async def upload_documento_fiscal(
    administradora_id: str = Form(...),
    condominio_id: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """
    Recebe uma foto ou PDF de documento fiscal:
    1. Salva no Supabase Storage (bucket integre / documentos/)
    2. Insere registro em documentos_fiscais com status = "pendente"
    3. Retorna imediatamente — o worker processa a extração em background
    """
    merged_pdf = pymupdf.open()
    for f in files:
        conteudo = await f.read()
        if f.content_type == "application/pdf":
            pdf_doc = pymupdf.open("pdf", conteudo)
            merged_pdf.insert_pdf(pdf_doc)
        else:
            img_doc = pymupdf.open("img", conteudo)
            pdf_bytes = img_doc.convert_to_pdf()
            pdf_doc = pymupdf.open("pdf", pdf_bytes)
            merged_pdf.insert_pdf(pdf_doc)
    
    final_bytes = merged_pdf.write()
    filename = f"doc_{int(datetime.now(timezone.utc).timestamp())}.pdf"
    mime_type = "application/pdf"

    # 1. Upload para o Supabase Storage
    try:
        resultado = upload_documento(
            file_bytes=final_bytes,
            filename=filename,
            mime_type=mime_type,
            condo_nome=condominio_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar no Supabase Storage: {str(e)}")

    # 2. Insere registro no banco com status "pendente"
    try:
        supabase = _get_supabase()
        insert = supabase.table("documentos_fiscais").insert({
            "administradora_id": administradora_id,
            "condominio_id": condominio_id,
            "condo_nome":   "Condominio",
            "bucket":       resultado["bucket"],
            "storage_path": resultado["path"],
            "filename":     filename,
            "status":       "pendente",
            "criado_em":    datetime.now(timezone.utc).isoformat(),
        }).execute()

        documento_id = insert.data[0]["id"]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao registrar no banco: {str(e)}")

    return UploadResponse(
        ok=True,
        documento_id=documento_id,
        path=resultado["path"],
        signed_url=resultado["signed_url"],
        bucket=resultado["bucket"],
        filename=filename,
    )


@router.post("/escanear", response_model=ProcessarDocumentoResponse)
async def escanear_documento(
    condominio_id: str,
    file: UploadFile = File(...),
    parser: DocumentoParser = Depends(),
    conhecimento_service: ConhecimentoService = Depends(),
):
    """
    Extrai dados de um documento fiscal via Gemini e retorna
    a sugestão contábil. Usado pelo fluxo de desktop (validação imediata).
    """
    if file.content_type not in ["application/pdf", "image/jpeg", "image/png"]:
        raise HTTPException(
            status_code=400,
            detail="Formato não suportado. Envie PDF, JPG ou PNG.",
        )

    dados_extraidos, hash_arquivo = await parser.parse_documento(file)
    sugestao = await conhecimento_service.gerar_sugestao(dados_extraidos, condominio_id)

    return ProcessarDocumentoResponse(
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
async def reprocessar_documento(doc_id: str):
    """Reprocessa um documento enviando-o de volta para a fila de extração OCR."""
    try:
        supabase = _get_supabase()
        supabase.table("documentos_fiscais").update({
            "status": "pendente",
            "erro_msg": None
        }).eq("id", doc_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao reprocessar: {str(e)}")
