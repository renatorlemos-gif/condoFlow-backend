import os

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel

from src.utils.documento_parser import DocumentoParser, DadosExtraidosDTO
from src.utils.supabase_storage import upload_documento
from src.services.conhecimento_service import ConhecimentoService, SugestaoContabilDTO
from src.services.lote_service import LoteService, ItemLoteContabil

router = APIRouter(prefix="/api/v1/documentos", tags=["Documentos & Lote Contábil"])


# ------------------------------------------------------------------ #
#  Schemas                                                            #
# ------------------------------------------------------------------ #

class ProcessarDocumentoResponse(BaseModel):
    hash_arquivo: str
    dados_extraidos: DadosExtraidosDTO
    sugestao_contabil: SugestaoContabilDTO


class UploadResponse(BaseModel):
    ok: bool
    path: str
    signed_url: str
    pasta: str
    filename: str


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

@router.post("/upload", response_model=UploadResponse)
async def upload_documento_fiscal(
    file: UploadFile = File(...),
):
    """
    Recebe uma foto ou PDF de documento fiscal e salva no Supabase Storage
    (bucket `documentos`) com um nome contextualizado:

        {condo-slug}_{YYYY-MM-DD}_{uuid}_{filename_original}

    Retorna imediatamente após o upload — o celular já pode fotografar
    o próximo documento.

    A extração de dados (Gemini) e persistência no banco serão adicionadas
    em segundo plano quando o schema do banco estiver definido.
    """
    conteudo   = await file.read()
    filename   = file.filename or "documento"
    mime_type  = file.content_type or "application/octet-stream"
    condo_nome = os.environ.get("CONDO_NOME", "Condominio")

    try:
        resultado = upload_documento(
            file_bytes=conteudo,
            filename=filename,
            mime_type=mime_type,
            condo_nome=condo_nome,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar no Supabase: {str(e)}")

    return UploadResponse(
        ok=True,
        path=resultado["path"],
        signed_url=resultado["signed_url"],
        pasta=resultado["pasta"],
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