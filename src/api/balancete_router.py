import os
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from supabase import create_client, Client
from src.services.pdf_parser_service import extract_balancete_data

router = APIRouter(prefix="/api/balancetes", tags=["Balancetes"])

@router.post("/upload")
async def upload_balancete(
    file: UploadFile = File(...),
    administradora_id: str = Form(...),
    condominio_id: str = Form(...)
):
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    
    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=500, detail="Variáveis de ambiente do Supabase não configuradas.")
        
    supabase: Client = create_client(supabase_url, supabase_key)
    
    try:
        pdf_bytes = await file.read()
        
        data = await extract_balancete_data(pdf_bytes)
        
        records_to_insert = []
        for item in data:
            records_to_insert.append({
                "condominio_id": condominio_id,
                "administradora_id": administradora_id,
                "fornecedor_nome": str(item.get("fornecedor_nome", "Desconhecido"))[:255],
                "conta_codigo": str(item.get("conta_codigo", ""))[:50] if item.get("conta_codigo") else None,
                "valor_referencia": float(item.get("valor_referencia", 0.0))
            })
            
        if records_to_insert:
            response = supabase.table("balancetes_historicos").insert(records_to_insert).execute()
            
        return {
            "status": "success", 
            "inserted": len(records_to_insert), 
            "data": records_to_insert
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
