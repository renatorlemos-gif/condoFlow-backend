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
            
            try:
                admin_ids = list(set([chave[0] for chave, _ in lote]))
                contas = list(set([chave[1] for chave, _ in lote]))
                
                resp = supabase.table("plano_contas").select("administradora_id,codigo,contexto").in_("administradora_id", admin_ids).in_("codigo", contas).execute()
                contextos_atuais = {}
                for row in (resp.data or []):
                    contextos_atuais[(str(row["administradora_id"]), str(row["codigo"]))] = row.get("contexto", "")
            except Exception as e:
                logger.error(f"Erro ao buscar contextos atuais: {e}")
                contextos_atuais = {}
            
            dados_para_ia = []
            for idx, (chave, grupo_data) in enumerate(lote):
                admin_id, conta = chave
                contexto_atual = contextos_atuais.get((str(admin_id), str(conta)), "")
                dados_para_ia.append({
                    "id": idx,
                    "conta": conta,
                    "descricoes": list(grupo_data["descricoes"]),
                    "contexto_atual": contexto_atual
                })
                
            prompt = (
                "Analise a lista de contas e descrições de balancetes a seguir.\n"
                "Para cada conta, sintetize um 'contexto' geral consolidado (máximo 300 caracteres) com base nas descrições fornecidas.\n"
                "INSTRUÇÃO IMPORTANTE SOBRE CONTEXTO ATUAL: Se a conta já possuir um 'contexto_atual' preenchido, você DEVE realizar um MERGE. "
                "Isto é, integre as novas descrições ao contexto antigo sem perder a essência do que já havia sido consolidado antes. "
                "O resultado deve ser a evolução do contexto (somando as novas informações ao contexto existente), e não uma substituição cega.\n"
                "INSTRUÇÃO ESTRITA: Você DEVE abstrair e omitir quaisquer nomes de prestadores de serviço, empresas, pessoas, datas, meses e locais específicos. "
                "O contexto gerado deve ser uma definição genérica, conceitual e abrangente sobre a natureza da despesa contábil "
                "(Ex: em vez de 'reparo na garagem por Tarcisio', gere 'Despesas com contratação de mão-de-obra autônoma ou terceirizada para reparos e manutenção em geral').\n"
                "Responda EXATAMENTE com um objeto JSON contendo um array 'resultados' com os contextos processados.\n"
                "Formato esperado:\n"
                "{\n"
                '  "resultados": [\n'
                '    {"id": 0, "contexto": "síntese genérica aqui sem nomes"},\n'
                '    {"id": 1, "contexto": "síntese genérica aqui sem nomes"}\n'
                "  ]\n"
                "}\n\n"
                f"Lista: {json.dumps(dados_para_ia, ensure_ascii=False)}"
            )
            
            try:
                # Cenário 04: Enviar ao Gemini pedindo a síntese em lote
                def chamar_gemini():
                    return client.models.generate_content(
                        model="gemini-3.1-flash-lite",
                        contents=[prompt],
                        config=types.GenerateContentConfig(
                            temperature=0.0,
                            response_mime_type="application/json"
                        )
                    )
                
                resp = await asyncio.to_thread(chamar_gemini)
                texto = resp.text.strip()
                try:
                    resp_json = json.loads(texto)
                except json.JSONDecodeError:
                    if texto.startswith("```json"):
                        texto = texto.replace("```json", "", 1)
                    elif texto.startswith("```"):
                        texto = texto.replace("```", "", 1)
                    if texto.endswith("```"):
                        texto = texto[:-3]
                    texto = texto.strip()
                    resp_json = json.loads(texto)
                    
                resultados_list = resp_json.get("resultados", []) if isinstance(resp_json, dict) else (resp_json if isinstance(resp_json, list) else [])
                contextos_por_id = {item.get("id"): item.get("contexto", "") for item in resultados_list if isinstance(item, dict) and "id" in item}
                
                contextos_lote = []
                textos_vetores_lote = []
                for idx, (chave, grupo_data) in enumerate(lote):
                    contexto = contextos_por_id.get(idx, "")
                    if not contexto:
                        contexto = "Contexto não gerado pela IA"
                    else:
                        contexto = str(contexto)[:300]
                    contextos_lote.append(contexto)
                    
                    conta_descricao = grupo_data.get("conta_descricao") or "Conta Contábil"
                    texto_vetor = f"{conta_descricao} - {contexto}"
                    textos_vetores_lote.append(texto_vetor)
                    
                def chamar_embeddings_individuais():
                    embeddings = []
                    for texto_individual in textos_vetores_lote:
                        resp = client.models.embed_content(
                            model='gemini-embedding-2',
                            contents=texto_individual,
                            config=types.EmbedContentConfig(output_dimensionality=768)
                        )
                        embeddings.append(list(resp.embeddings[0].values))
                    return embeddings
                
                embeddings_lote = await asyncio.to_thread(chamar_embeddings_individuais)
                
                for idx, (chave, grupo_data) in enumerate(lote):
                    admin_id, conta = chave
                    contexto = contextos_lote[idx]
                    embedding_val = embeddings_lote[idx]
                        
                    # Fazer o UPSERT na tabela plano_contas
                    upsert_data = {
                        "administradora_id": str(admin_id),
                        "codigo": conta,
                        "descricao": grupo_data.get("conta_descricao") or "Conta Contábil",
                        "contexto": contexto,
                        "embedding": embedding_val,
                        "criada_por_ia": True
                    }
                    
                    try:
                        supabase.table("plano_contas").upsert(
                            upsert_data, 
                            on_conflict="administradora_id,codigo"
                        ).execute()
                    except Exception as e:
                        logger.error(f"Erro no upsert de plano_contas: {e}")
                        
                    # Atualiza processado_ia
                    ids_to_update = grupo_data["ids"]
                    if ids_to_update:
                        for chunk_i in range(0, len(ids_to_update), 50):
                            chunk_ids = ids_to_update[chunk_i:chunk_i+50]
                            supabase.table("balancetes_historicos").update({"processado_ia": True}).in_("id", chunk_ids).execute()
                    
                    resultados.append({
                        "conta": conta,
                        "conta_descricao": grupo_data.get("conta_descricao"),
                        "contexto": contexto
                    })
                    
            except Exception as e:
                # Cenário 05: Aplicar resiliência (timeout ou falha não quebra o loop)
                logger.error(f"Erro ao processar lote: {e}")
                erros += len(lote)
            
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

