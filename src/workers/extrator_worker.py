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
import os
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

        # 2. Busca Regra Fixa no BD
        regra = None
        if dados.nome_fornecedor:
            res_regra = supabase.table("regras_contabeis").select("*").ilike("fornecedor_nome", f"%{dados.nome_fornecedor}%").limit(1).execute()
            if res_regra.data:
                regra = res_regra.data[0]
        
        conta_codigo = None
        historico_sugerido = f"Vlr. ref. {dados.descricao or 'serviços prestados'} - {dados.nome_fornecedor or ''}"
        
        if regra:
            conta_codigo = regra["conta_codigo"]
            score = 0.95
        else:
            # 3. Se não achar, usa gemini-3.5-flash passando histórico/plano
            try:
                from google import genai
                client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
                prompt_classificacao = f"Você é um assistente contábil. Dado o fornecedor '{dados.nome_fornecedor}' e descrição '{dados.descricao}', sugira APENAS o código da conta contábil mais apropriada (ex: '3.1.09.99'). Se não tiver certeza, retorne '3.1.09.99'."
                resp = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=[prompt_classificacao]
                )
                conta_codigo = resp.text.strip()
                score = 0.70
            except Exception as e:
                logger.error(f"Erro no motor de classificação Gemini: {e}")
                conta_codigo = "3.1.09.99"
                score = 0.50

        sugestao_json = {
            "conta_debito_codigo":  conta_codigo,
            "conta_debito_nome":    "Conta Classificada",
            "conta_credito_codigo": "1.1.01.02",
            "conta_credito_nome":   "Banco Conta Movimento",
            "historico_sugerido":   historico_sugerido,
            "score_confianca":      score,
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
                .select("id, bucket, storage_path, filename, condo_nome")
                .eq("status", "pendente")
                .order("criado_em")
                .limit(5)
                .execute()
            )

            docs = result.data or []

            if docs:
                logger.info(f"[worker] {len(docs)} documento(s) pendente(s)")
                for doc in docs:
                    await _processar_documento(supabase, doc)
            else:
                logger.debug("[worker] nenhum documento pendente")

        except Exception as e:
            logger.error(f"[worker] erro no ciclo: {e}")

        await asyncio.sleep(intervalo)
