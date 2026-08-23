from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from pydantic import BaseModel

from src.utils.documento_parser import DocumentoParser, DadosExtraidosDTO
from src.services.conhecimento_service import ConhecimentoService, SugestaoContabilDTO
from src.services.lote_service import LoteService, ItemLoteContabil

router = APIRouter(prefix="/api/v1/documentos", tags=["Documentos & Lote Contábil"])

class ProcessarDocumentoResponse(BaseModel):
    hash_arquivo: str
    dados_extraidos: DadosExtraidosDTO
    sugestao_contabil: SugestaoContabilDTO

@router.post("/escanear", response_model=ProcessarDocumentoResponse)
async def escanear_documento(
    condominio_id: str,
    file: UploadFile = File(...),
    parser: DocumentoParser = Depends(),
    conhecimento_service: ConhecimentoService = Depends()
):
    if file.content_type not in ["application/pdf", "image/jpeg", "image/png"]:
        raise HTTPException(status_code=400, detail="Formato não suportado. Envie PDF, JPG ou PNG.")

    dados_extraidos, hash_arquivo = await parser.parse_documento(file)
    sugestao = await conhecimento_service.gerar_sugestao(dados_extraidos, condominio_id)

    return ProcessarDocumentoResponse(
        hash_arquivo=hash_arquivo,
        dados_extraidos=dados_extraidos,
        sugestao_contabil=sugestao
    )

@router.post("/lote/adicionar", response_model=ItemLoteContabil)
async def adicionar_ao_lote(
    item: ItemLoteContabil,
    lote_service: LoteService = Depends()
):
    # Salva o item validado/ajustado pelo usuário
    return item