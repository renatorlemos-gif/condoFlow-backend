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
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Arquivo recebido: nome={file.filename}, tipo={file.content_type}, tamanho={getattr(file, 'size', 'desconhecido')}")
        await file.seek(0)
        pdf_bytes = await file.read()
        logger.info(f"Bytes lidos após seek(0): {len(pdf_bytes)}")
        
        data = await extract_balancete_data(pdf_bytes)
        
        records_to_insert = []
        for item in data:
            records_to_insert.append({
                "condominio_id": condominio_id,
                "administradora_id": administradora_id,
                "fornecedor_nome": str(item.get("fornecedor_nome", "Desconhecido"))[:255],
                "conta_codigo": str(item.get("conta_codigo", ""))[:50] if item.get("conta_codigo") else None,
                "conta_descricao": str(item.get("conta_descricao", ""))[:255] if item.get("conta_descricao") else None,
                "valor_referencia": float(item.get("valor_referencia", 0.0))
            })
            
        if records_to_insert:
            response = supabase.table("balancetes_historicos").insert(records_to_insert).execute()
            
            import re
            for item in data:
                fornec_norm = str(item.get("fornecedor_nome", "")).strip().upper()
                fornec_norm = re.sub(r'\s+', ' ', fornec_norm)
                
                desc_norm = str(item.get("conta_descricao", "")).strip().upper()
                desc_norm = re.sub(r'\s+', ' ', desc_norm)
                
                conta_codigo = str(item.get("conta_codigo", ""))[:50] if item.get("conta_codigo") else None
                
                if conta_codigo and fornec_norm:
                    try:
                        res = supabase.table("regras_de_para").select("id, frequencia").eq("condominio_id", condominio_id).eq("fornecedor", fornec_norm).eq("descricao_servico", desc_norm).eq("conta_codigo", conta_codigo).execute()
                        if res.data:
                            freq = res.data[0].get("frequencia", 1) + 1
                            supabase.table("regras_de_para").update({"frequencia": freq}).eq("id", res.data[0]["id"]).execute()
                        else:
                            supabase.table("regras_de_para").insert({
                                "condominio_id": condominio_id,
                                "administradora_id": administradora_id,
                                "fornecedor": fornec_norm,
                                "descricao_servico": desc_norm,
                                "conta_codigo": conta_codigo,
                                "frequencia": 1,
                                "origem": "balancete"
                            }).execute()
                    except Exception as e:
                        logger.error(f"Erro ao inserir regras_de_para: {e}")
            
        return {
            "status": "success", 
            "inserted": len(records_to_insert), 
            "data": records_to_insert
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
