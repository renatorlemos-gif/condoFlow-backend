import os
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from supabase import create_client
import io

from src.services.exportador_service import ExportadorService
from src.utils.supabase_storage import _slugify

router = APIRouter(prefix="/api/v1/exportacao", tags=["Exportação"])

def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)


def _formatar_competencia(comp: str) -> str:
    """Formata competência para MM-AAAA (ex: 2026-10 -> 10-2026; 10/2026 -> 10-2026)."""
    if not comp:
        return ""
    comp = comp.strip().replace("/", "-")
    partes = comp.split("-")
    if len(partes) == 2:
        p1, p2 = partes[0].strip(), partes[1].strip()
        if len(p1) == 4 and p1.isdigit():
            return f"{p2.zfill(2)}-{p1}"
        elif len(p2) == 4 and p2.isdigit():
            return f"{p1.zfill(2)}-{p2}"
    return comp


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
        
        # Buscar condomínio e administradora para gerar nome padronizado
        nome_condo = None
        nome_adm = None
        try:
            condo_resp = supabase.table("condominios").select("nome, administradora_id").eq("id", condominio_id).limit(1).execute()
            if condo_resp.data and len(condo_resp.data) > 0:
                condo_data = condo_resp.data[0]
                nome_condo = condo_data.get("nome")
                adm_id = condo_data.get("administradora_id")
                if adm_id:
                    adm_resp = supabase.table("administradoras").select("nome").eq("id", adm_id).limit(1).execute()
                    if adm_resp.data and len(adm_resp.data) > 0:
                        nome_adm = adm_resp.data[0].get("nome")
        except Exception:
            pass

        slug_adm = (_slugify(nome_adm) if nome_adm else "") or "administradora"
        slug_condo = (_slugify(nome_condo) if nome_condo else "") or (_slugify(condominio_id) or "condominio")
        mes_ano = _formatar_competencia(competencia)
        filename = f"{slug_adm}_{slug_condo}_{mes_ano}.txt"

        buffer = io.BytesIO(csv_bytes)
        return StreamingResponse(
            buffer,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


