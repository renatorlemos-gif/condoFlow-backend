import os
import io
import pandas as pd
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from supabase import create_client
import logging

logger = logging.getLogger("plano_contas")

router = APIRouter(prefix="/api/plano-contas", tags=["Plano de Contas"])

def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)

@router.post("/upload")
async def upload_plano_contas(
    file: UploadFile = File(...),
    administradora_id: str = Form(...)
):
    """
    Recebe um arquivo Excel ou CSV com o plano de contas da administradora.
    O arquivo deve conter as colunas: 'codigo', 'descricao', 'tipo' (opcional).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo não enviado.")
    
    conteudo_bytes = await file.read()
    
    try:
        if file.filename.endswith(".csv"):
            df = None
            for enc in ['utf-8', 'utf-8-sig', 'utf-16', 'latin1']:
                try:
                    df = pd.read_csv(io.BytesIO(conteudo_bytes), encoding=enc, sep=None, engine='python')
                    break
                except UnicodeError:
                    continue
            if df is None:
                df = pd.read_csv(io.BytesIO(conteudo_bytes), encoding='utf-8', errors='replace', sep=None, engine='python')
        elif file.filename.endswith((".xls", ".xlsx")):
            df = pd.read_excel(io.BytesIO(conteudo_bytes))
        else:
            raise ValueError("Formato de arquivo não suportado. Use CSV ou Excel.")
            
        # Normalização de colunas
        df.columns = [str(c).strip().lower() for c in df.columns]
        
        if "codigo" not in df.columns or "descricao" not in df.columns:
            raise ValueError("O arquivo deve conter as colunas 'codigo' e 'descricao'.")
            
        if "tipo" not in df.columns:
            df["tipo"] = "analitica"
            
        # Limpar nulos
        df = df.dropna(subset=["codigo", "descricao"])
        
        inserts = []
        for _, row in df.iterrows():
            inserts.append({
                "administradora_id": administradora_id,
                "codigo": str(row["codigo"]).strip(),
                "descricao": str(row["descricao"]).strip(),
                "tipo": str(row["tipo"]).strip() if pd.notnull(row["tipo"]) else "analitica"
            })
            
        if not inserts:
            raise ValueError("Nenhum registro válido encontrado no arquivo.")
            
        supabase = _get_supabase()
        
        # Não deletamos a tabela toda para preservar 'contexto' e 'embedding' das regras semânticas
        # Faz upsert baseado na chave composta (administradora_id, codigo)
        
        # Inserir em lotes de 1000
        batch_size = 1000
        for i in range(0, len(inserts), batch_size):
            batch = inserts[i:i+batch_size]
            supabase.table("plano_contas").upsert(batch, on_conflict="administradora_id,codigo").execute()
            
        return {"mensagem": f"{len(inserts)} contas carregadas com sucesso.", "quantidade": len(inserts)}
        
    except Exception as e:
        logger.error(f"Erro ao processar plano de contas: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/")
async def get_plano_contas(administradora_id: str):
    """Retorna o plano de contas atual de uma administradora"""
    try:
        supabase = _get_supabase()
        response = supabase.table("plano_contas").select("*").eq("administradora_id", administradora_id).order("codigo").execute()
        return {"data": response.data}
    except Exception as e:
        logger.error(f"Erro ao buscar plano de contas: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar plano de contas.")
