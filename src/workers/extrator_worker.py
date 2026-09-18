"""
extrator_worker.py
==================
Worker de extração em segundo plano.

Fluxo a cada ciclo:
  1. Busca documentos com status = "pendente" no banco
  2. Marca como "extraindo" (evita processamento duplicado)
  3. Baixa o arquivo do Supabase Storage
  4. Chama o Gemini via DocumentoParser para extrair os dados
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


async def _processar_documento(supabase, doc: dict) -> None:
    doc_id       = doc["id"]
    storage_path = doc["storage_path"]
    bucket       = doc["bucket"]

    logger.info(f"[worker] processando documento {doc_id} — {storage_path}")

    try:
        # Marca como "extraindo" para evitar reprocessamento paralelo
        supabase.table("documentos_fiscais").update({
            "status": "extraindo",
        }).eq("id", doc_id).execute()

        # Baixa o arquivo do Supabase Storage
        file_bytes = supabase.storage.from_(bucket).download(storage_path)

        # Detecta mime type pela extensão
        ext = storage_path.rsplit(".", 1)[-1].lower()
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "pdf": "application/pdf"}
        mime_type = mime_map.get(ext, "application/octet-stream")

        # Cria um UploadFile simulado para o DocumentoParser
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

            from src.utils.documento_parser import DocumentoParser
            parser = DocumentoParser()
            dados, hash_arquivo = await parser.parse_documento(upload)

        # Remove arquivo temporário
        os.unlink(tmp_path)

        # 2. RAG para classificação contábil
        conta_codigo = None
        conta_nome = "Conta Classificada"
        desc_segura = getattr(dados, "descricao", None) or "serviços prestados"
        fornec_seguro = getattr(dados, "nome_fornecedor", None) or ""
        historico_sugerido = f"Vlr. ref. {desc_segura} - {fornec_seguro}"
        score = 0.0
        origem_sugestao = "gemini_inferencia"
        
        try:
            admin_id = doc.get("administradora_id")
            if admin_id:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                
                texto_busca = f"{fornec_seguro} {desc_segura}".strip()
                
                # Gera embedding
                for attempt in range(1, 4):
                    try:
                        emb_res = client.models.embed_content(
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
                
                # Busca regras no Supabase via vetor
                # Busca regras no Supabase via vetor
                res_rag = supabase.rpc("match_plano_contas", {
                    "query_embedding": list(embedding),
                    "match_threshold": 0.4,
                    "match_count": 5,
                    "p_administradora_id": str(admin_id)
                }).execute()
                
                if res_rag.data:
                    top_match = res_rag.data[0]
                    # Fast Path relaxado para poupar requisições: se similaridade boa, não chama o Gemini
                    sim = top_match.get('similarity')
                    if sim is None:
                        sim = 0.0
                    elif isinstance(sim, str) and sim.lower() == 'nan':
                        sim = 0.0
                    elif isinstance(sim, float) and math.isnan(sim):
                        sim = 0.0
                    else:
                        sim = float(sim)
                    
                    if sim >= 0.70:
                        conta_codigo = top_match.get('codigo')
                        conta_nome = top_match.get('descricao', 'N/A')
                        score = top_match.get('similarity', 0.90)
                        origem_sugestao = "rag_fast_path"
                    else:
                        regras_str = ""
                        for r in res_rag.data:
                            regras_str += f"Código: {r.get('codigo')} | Conta: {r.get('descricao', 'N/A')} | Contexto: {r.get('contexto', 'N/A')}\n"
                        
                        prompt_classificacao = (
                            f"Você é um assistente contábil. Sua tarefa é julgar a regra contábil perfeita para este documento.\n\n"
                            f"FORNECEDOR DO DOCUMENTO: '{fornec_seguro}'\n"
                            f"DESCRIÇÃO DO DOCUMENTO: '{desc_segura}'\n\n"
                            f"Top 5 Regras Contábeis Sugeridas:\n{regras_str}\n\n"
                            f"Julgue qual destas 5 regras é a perfeita para a Nota Fiscal.\n"
                            f"Responda APENAS com o 'Código' da conta escolhida. Se NENHUMA servir, devolva 'nulo'."
                        )
                        
                        for attempt in range(1, 4):
                            try:
                                resp = client.models.generate_content(
                                    model="gemini-3.1-flash-lite",
                                    contents=[prompt_classificacao],
                                    config=types.GenerateContentConfig(temperature=0.0)
                                )
                                break
                            except Exception as e:
                                if attempt < 3 and ("503" in str(e) or "429" in str(e)):
                                    await asyncio.sleep(2 ** attempt)
                                else:
                                    raise e
                        
                        sugestao = resp.text.strip()
                        if sugestao.lower() not in ("null", "nulo", "vazio", "none", ""):
                            conta_codigo = sugestao
                            score = top_match.get('similarity', 0.80) # Use similarity of the best match as base
                            origem_sugestao = "rag_gemini_arbitration"
                            
                            nome_res = supabase.table("plano_contas").select("descricao").eq("administradora_id", str(admin_id)).eq("codigo", conta_codigo).execute()
                            if nome_res.data:
                                conta_nome = nome_res.data[0]["descricao"]
                        else:
                            # FALLBACK: O Gemini refugou. Use o top_match obrigatóriamente!
                            conta_codigo = top_match.get('codigo')
                            conta_nome = top_match.get('descricao', 'N/A')
                            score = top_match.get('similarity', 0.0)
                            origem_sugestao = "rag_fallback_top_score"
                else:
                    origem_sugestao = "rag_sem_resultado"
        except Exception as e:
            logger.error(f"Erro no fluxo RAG: {e}\n{traceback.format_exc()}")
            conta_codigo = None
            score = 0.0
            origem_sugestao = "rag_erro"

        sugestao_json = {
            "conta_debito_codigo":  conta_codigo,
            "conta_debito_nome":    conta_nome if conta_codigo else None,
            "conta_credito_codigo": "1.1.01.02" if conta_codigo else None,
            "conta_credito_nome":   "Banco Conta Movimento" if conta_codigo else None,
            "historico_sugerido":   historico_sugerido,
            "score_confianca":      score,
            "origem_sugestao":      origem_sugestao,
        }

        def _clean_date(d):
            if not d or str(d).lower().strip() in ("null", "none", ""):
                return None
            return d

        # Atualiza o registro no banco
        supabase.table("documentos_fiscais").update({
            "status":            "extraido",
            "fornecedor":        dados.nome_fornecedor,
            "cnpj_cpf":          dados.cnpj_cpf_fornecedor,
            "numero_doc":        dados.numero_documento,
            "data_emissao":      _clean_date(dados.data_emissao),
            "data_vencimento":   _clean_date(dados.data_vencimento),
            "data_pagamento":    _clean_date(dados.data_pagamento),
            "valor_total":       dados.valor_total,
            "descricao":         dados.descricao,
            "hash_arquivo":      hash_arquivo,
            "sugestao_contabil": sugestao_json,
            "extraido_em":       datetime.now(timezone.utc).isoformat(),
            "erro_msg":          None,
        }).eq("id", doc_id).execute()

        logger.info(f"[worker] documento {doc_id} extraído com sucesso")

    except Exception as e:
        logger.error(f"[worker] erro ao processar {doc_id}: {e}")
        supabase.table("documentos_fiscais").update({
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

            # Busca documentos pendentes (máx 5 por ciclo para não sobrecarregar)
            result = (
                supabase.table("documentos_fiscais")
                .select("id, bucket, storage_path, filename, condo_nome, condominio_id, administradora_id")
                .in_("status", ["pendente", "extraindo"])
                .order("criado_em")
                .limit(5)
                .execute()
            )

            docs = result.data or []

            if docs:
                logger.info(f"[worker] {len(docs)} documento(s) na fila (pendente/extraindo)")
                for doc in docs:
                    await _processar_documento(supabase, doc)
            else:
                logger.debug("[worker] nenhum documento na fila")

        except Exception as e:
            logger.error(f"[worker] erro no ciclo: {e}")

        await asyncio.sleep(intervalo)
