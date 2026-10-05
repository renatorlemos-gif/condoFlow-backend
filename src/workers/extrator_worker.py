"""
extrator_worker.py
==================
Worker de extração em segundo plano.

Fluxo a cada ciclo:
  1. Busca despesas com status = "pendente" no banco
  2. Marca como "extraindo" (evita processamento duplicado)
  3. Baixa o arquivo do Supabase Storage
  4. Chama o Gemini via DespesaParser para extrair os dados
  5. Atualiza o registro com os dados extraídos + status = "extraido"
  6. Em caso de erro, marca status = "erro" e registra a mensagem

Roda como asyncio task em background junto com o Uvicorn.
Intervalo configurável via env var WORKER_INTERVAL_SECONDS (default: 30).
"""

import asyncio
import io
import logging
import math
import os
import traceback
from datetime import datetime, timezone

from supabase import create_client

logger = logging.getLogger("extrator_worker")


def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)


async def _processar_despesa(supabase, doc: dict) -> None:
    doc_id       = doc["id"]
    storage_path = doc["storage_path"]
    bucket       = doc["bucket"]

    logger.info(f"[worker] processando despesa {doc_id} — {storage_path}")

    try:
        # Marca como "extraindo" para evitar reprocessamento paralelo
        def _update_extraindo():
            supabase.table("despesas").update({
                "status": "extraindo",
            }).eq("id", doc_id).execute()
        
        await asyncio.to_thread(_update_extraindo)

        # Baixa o arquivo do Supabase Storage
        file_bytes = await asyncio.to_thread(
            supabase.storage.from_(bucket).download,
            storage_path
        )

        # Detecta mime type pela extensão
        ext = storage_path.rsplit(".", 1)[-1].lower()
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "pdf": "application/pdf"}
        mime_type = mime_map.get(ext, "application/octet-stream")

        # Cria um UploadFile simulado para o DespesaParser
        from fastapi import UploadFile
        from starlette.datastructures import UploadFile as StarletteUploadFile
        import tempfile

        # Escreve em arquivo temporário para compatibilidade com UploadFile
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # Usa o SpooledTemporaryFile do Starlette
        with open(tmp_path, "rb") as f:
            upload = StarletteUploadFile(
                filename=doc["filename"],
                file=io.BytesIO(file_bytes),
                headers={"content-type": mime_type},
            )

            from src.utils.despesa_parser import DespesaParser
            parser = DespesaParser()
            dados, hash_arquivo = await parser.parse_despesa(upload)

        # Remove arquivo temporário
        os.unlink(tmp_path)

        # 2. RAG para classificação contábil
        codigo_contabil = None
        conta_nome = "Conta Classificada"
        desc_segura = getattr(dados, "descricao", None) or "serviços prestados"
        fornec_seguro = getattr(dados, "nome_fornecedor", None) or ""
        contexto_sintetizado = getattr(dados, "contexto_sintetizado", None) or f"{fornec_seguro} {desc_segura}".strip()
        historico_sugerido = f"Vlr. ref. {desc_segura} - {fornec_seguro}"
        score = 0.0
        origem_sugestao = "gemini_inferencia"
        embedding_val = None
        
        try:
            admin_id = doc.get("administradora_id")
            if admin_id:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                
                desc_para_ancora = getattr(dados, "descricao", "") or ""
                texto_busca = f"{desc_para_ancora} - {contexto_sintetizado}"
                
                # Gera embedding
                for attempt in range(1, 4):
                    try:
                        emb_res = await asyncio.to_thread(
                            client.models.embed_content,
                            model="gemini-embedding-2",
                            contents=texto_busca,
                            config=types.EmbedContentConfig(output_dimensionality=768)
                        )
                        break
                    except Exception as e:
                        if attempt < 3 and ("503" in str(e) or "429" in str(e)):
                            await asyncio.sleep(2 ** attempt)
                        else:
                            raise e
                embedding = emb_res.embeddings[0].values
                embedding_val = embedding
                
                # Busca regras no Supabase via vetor
                def _exec_rpc():
                    return supabase.rpc("match_plano_contas", {
                        "query_embedding": list(embedding),
                        "match_threshold": 0.0,
                        "match_count": 5,
                        "p_administradora_id": str(admin_id)
                    }).execute()
                res_rag = await asyncio.to_thread(_exec_rpc)
                
                if res_rag.data:
                    top_match = res_rag.data[0]
                    codigo_contabil = top_match.get('codigo_contabil')
                    conta_nome = top_match.get('descricao', 'N/A')
                    
                    sim = top_match.get('similarity')
                    if sim is None or str(sim).lower() == 'nan' or (isinstance(sim, float) and math.isnan(sim)):
                        score = 0.0
                    else:
                        score = float(sim)
                    
                    origem_sugestao = "rag_hyde_match"
                else:
                    origem_sugestao = "rag_sem_resultado"
        except Exception as e:
            logger.error(f"Erro no fluxo RAG: {e}\n{traceback.format_exc()}")
            codigo_contabil = None
            score = 0.0
            origem_sugestao = "rag_erro"

        sugestao_json = {
            "conta_debito_codigo":  codigo_contabil,
            "conta_debito_nome":    conta_nome if codigo_contabil else None,
            "conta_credito_codigo": "1.1.01.02" if codigo_contabil else None,
            "conta_credito_nome":   "Banco Conta Movimento" if codigo_contabil else None,
            "historico_sugerido":   historico_sugerido,
            "score_confianca":      score,
            "origem_sugestao":      origem_sugestao,
        }

        def _clean_date(d):
            if not d or str(d).lower().strip() in ("null", "none", ""):
                return None
            return d

        # Atualiza o registro no banco
        update_data = {
            "status":            "extraido",
            "fornecedor":        dados.nome_fornecedor,
            "cnpj_cpf":          dados.cnpj_cpf_fornecedor,
            "numero_doc":        dados.numero_despesa,
            "data_emissao":      _clean_date(dados.data_emissao),
            "data_vencimento":   _clean_date(dados.data_vencimento),
            "data_pagamento":    _clean_date(dados.data_pagamento),
            "valor_total":       dados.valor_total,
            "descricao":         dados.descricao,
            "hash_arquivo":      hash_arquivo,
            "sugestao_contabil": sugestao_json,
            "extraido_em":       datetime.now(timezone.utc).isoformat(),
            "erro_msg":          None,
            "contexto":          contexto_sintetizado,
            "chave_acesso":      getattr(dados, "chave_acesso", None),
            "competencia":       getattr(dados, "competencia", None),
        }
        if embedding_val:
            update_data["embedding"] = list(embedding_val)

        await asyncio.to_thread(lambda: supabase.table("despesas").update(update_data).eq("id", doc_id).execute())

        logger.info(f"[worker] despesa {doc_id} extraído com sucesso")

    except Exception as e:
        logger.error(f"[worker] erro ao processar {doc_id}: {e}")
        supabase.table("despesas").update({
            "status":   "erro",
            "erro_msg": str(e),
        }).eq("id", doc_id).execute()


async def rodar_worker() -> None:
    """Loop principal do worker. Chamado no startup do FastAPI."""
    intervalo = int(os.environ.get("WORKER_INTERVAL_SECONDS", "30"))
    logger.info(f"[worker] iniciado — intervalo: {intervalo}s")

    while True:
        try:
            supabase = _get_supabase()

            # Busca despesas pendentes (máx 5 por ciclo para não sobrecarregar)
            def _poll():
                return supabase.table("despesas").select("id, bucket, storage_path, filename, condominio_id, administradora_id").eq("status", "pendente").order("criado_em").limit(5).execute()
            
            result = await asyncio.to_thread(_poll)

            docs = result.data or []

            if docs:
                logger.info(f"[worker] {len(docs)} despesa(s) na fila (pendente)")
                for doc in docs:
                    await _processar_despesa(supabase, doc)
            else:
                logger.debug("[worker] nenhum despesa na fila")

        except Exception as e:
            logger.error(f"[worker] erro no ciclo: {e}")

        await asyncio.sleep(intervalo)
