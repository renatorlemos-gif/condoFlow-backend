import os

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel

from src.utils.documento_parser import DocumentoParser, DadosExtraidosDTO
from src.utils.supabase_storage import upload_documento
from src.utils.image_validator import validar_qualidade_imagem
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
    bucket: str
    filename: str


class QualidadeReprovadaResponse(BaseModel):
    ok: bool
    motivo: str


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

@router.post(
    "/upload",
    response_model=UploadResponse,
    responses={422: {"model": QualidadeReprovadaResponse, "description": "Imagem com qualidade insuficiente"}},
)
async def upload_documento_fiscal(
    file: UploadFile = File(...),
):
    """
    Recebe uma foto ou PDF de documento fiscal.

    Fluxo:
    1. Valida qualidade da imagem via Gemini (PDFs são aprovados automaticamente)
    2. Se aprovada: salva no Supabase Storage (bucket condominios / documentos/)
    3. Se reprovada: retorna 422 com o motivo — nenhum arquivo é salvo

    Nome do arquivo no storage:
        {condo-slug}_{YYYY-MM-DD}_{uuid8}_{filename_original}

    A extração de dados (Gemini) e persistência no banco serão adicionadas
    em segundo plano quando o schema do banco estiver definido.
    """
    conteudo  = await file.read()
    filename  = file.filename or "documento"
    mime_type = file.content_type or "application/octet-stream"

    # 1. Validação de qualidade
    try:
        validacao = validar_qualidade_imagem(conteudo, mime_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na validação de qualidade: {str(e)}")

    if not validacao.aprovada:
        raise HTTPException(
            status_code=422,
            detail=validacao.motivo or "Imagem com qualidade insuficiente para extração de dados.",
        )

    # 2. Upload para o Supabase
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
