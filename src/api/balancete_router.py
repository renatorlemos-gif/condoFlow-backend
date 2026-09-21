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
                "descricao_lancamento": str(item.get("descricao_lancamento", "Desconhecido"))[:255],
                "conta_codigo": str(item.get("conta_codigo", ""))[:50] if item.get("conta_codigo") else None,
                "conta_descricao": str(item.get("conta_descricao", ""))[:255] if item.get("conta_descricao") else None
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

from pydantic import BaseModel
from typing import Optional
from google import genai
from google.genai import types
import asyncio

class ProcessarRegrasRequest(BaseModel):
    administradora_id: Optional[str] = None

@router.post("/processar-regras")
async def processar_regras(request: ProcessarRegrasRequest = None):
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=500, detail="Variáveis de ambiente do Supabase não configuradas.")
    if not gemini_key:
        raise HTTPException(status_code=500, detail="Chave do Gemini não configurada.")
        
    supabase: Client = create_client(supabase_url, supabase_key)
    
    try:
        import logging
        logger = logging.getLogger(__name__)
        
        query = supabase.table("balancetes_historicos").select("id, administradora_id, descricao_lancamento, conta_codigo, conta_descricao").or_("processado_ia.is.null,processado_ia.eq.false")
        if request and request.administradora_id:
            query = query.eq("administradora_id", request.administradora_id)
            
        res = query.execute()
        data = res.data or []
        
        # Cenário 02: Agrupar por administradora_id e conta_codigo
        grupos = {}
        for item in data:
            item_id = item.get("id")
            admin_id = item.get("administradora_id")
            conta = item.get("conta_codigo")
            desc = item.get("descricao_lancamento")
            conta_descricao = item.get("conta_descricao")
            
            if not admin_id or not conta:
                continue
                
            chave = (admin_id, conta)
            if chave not in grupos:
                grupos[chave] = {"descricoes": set(), "ids": [], "conta_descricao": conta_descricao}
            if desc:
                grupos[chave]["descricoes"].add(desc)
            if item_id:
                grupos[chave]["ids"].append(item_id)
                
        import json
        client = genai.Client(api_key=gemini_key)
        resultados = []
        erros = 0
        
        grupos_list = list(grupos.items())
        batch_size = 20
        
        # Cenário 03: Loop assíncrono para cada lote de grupos
        for i in range(0, len(grupos_list), batch_size):
            lote = grupos_list[i:i+batch_size]
            
            from src.services.contexto_service import ContextoService
            for chave, grupo_data in lote:
                try:
                    admin_id, conta = chave
                    desc_join = " | ".join(list(grupo_data["descricoes"]))
                    
                    ContextoService.atualizar_contexto(supabase, str(admin_id), str(conta), desc_join)
                    
                    # Atualiza processado_ia
                    ids_to_update = grupo_data["ids"]
                    if ids_to_update:
                        for chunk_i in range(0, len(ids_to_update), 50):
                            chunk_ids = ids_to_update[chunk_i:chunk_i+50]
                            supabase.table("balancetes_historicos").update({"processado_ia": True}).in_("id", chunk_ids).execute()
                            
                    resultados.append({
                        "conta": conta,
                        "conta_descricao": grupo_data.get("conta_descricao"),
                        "contexto": "Atualizado via ContextoService"
                    })
                except Exception as e:
                    logger.error(f"Erro ao processar conta {conta}: {e}")
                    erros += 1
            
            # Pausa para aliviar o rate limit da API gratuita do Gemini
            await asyncio.sleep(2)
                
        return {
            "status": "success",
            "processados": len(resultados),
            "erros": erros,
            "detalhes": resultados
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

