import os
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from supabase import create_client
import io

from src.services.exportador_service import ExportadorService

router = APIRouter(prefix="/api/v1/exportacao", tags=["Exportação"])

def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)

@router.get("/lote")
async def exportar_lote_alterdata(
    condominio_id: str = Query(..., description="ID do condomínio para exportar os lançamentos conciliados"),
):
    try:
        supabase = _get_supabase()
        service = ExportadorService(supabase)
        csv_bytes = service.gerar_lote_alterdata(condominio_id)
        
        # Enviar como StreamingResponse
        buffer = io.BytesIO(csv_bytes)
        
        return StreamingResponse(
            buffer,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=lote_alterdata_{condominio_id}.csv"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno ao gerar lote: {str(e)}")

@router.get("/preview-us42")
async def preview_us42(
    condominio_id: str = Query(...),
    competencia: str = Query(...)
):
    supabase = _get_supabase()
    from src.services.exportador_service import ExportadorService
    service = ExportadorService(supabase)
    return service.obter_preview_us42(condominio_id, competencia)

@router.get("/lote-us42")
async def exportar_lote_us42(
    condominio_id: str = Query(...),
    competencia: str = Query(...)
):
    try:
        supabase = _get_supabase()
        from src.services.exportador_service import ExportadorService
        service = ExportadorService(supabase)
        csv_bytes = service.gerar_lote_us42(condominio_id, competencia)
        
        buffer = io.BytesIO(csv_bytes)
        return StreamingResponse(
            buffer,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=lote_alterdata_{condominio_id}_{competencia}.txt"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

