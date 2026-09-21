import os
import json
import logging
import math
from datetime import datetime, timezone
from google import genai
from google.genai import types
from typing import List, Optional

logger = logging.getLogger("contexto_service")

class ContextoService:
    @staticmethod
    def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2:
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    @staticmethod
    def atualizar_contexto(supabase, admin_id: str, conta_codigo: str, novo_descritivo: str):
        try:
            # 1. Puxa os dados da conta atual
            res = (
                supabase.table("plano_contas")
                .select("descricao, contexto, embedding")
                .eq("administradora_id", str(admin_id))
                .eq("codigo", conta_codigo)
                .execute()
            )
            
            if not res.data:
                logger.warning(f"[ContextoService] Conta {conta_codigo} no encontrada para a administradora {admin_id}.")
                return

            conta_data = res.data[0]
            conta_descricao = conta_data.get("descricao") or ""
            contexto_atual = conta_data.get("contexto") or ""
            embedding_atual = conta_data.get("embedding")
            
            if embedding_atual and isinstance(embedding_atual, str):
                try:
                    embedding_atual = json.loads(embedding_atual)
                except Exception:
                    embedding_atual = None

            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

            # Se ja existir embedding, verifica similaridade
            if embedding_atual:
                emb_res = client.models.embed_content(
                    model="gemini-embedding-2",
                    contents=novo_descritivo,
                    config=types.EmbedContentConfig(output_dimensionality=768)
                )
                novo_descritivo_embedding = emb_res.embeddings[0].values
                
                sim = ContextoService._cosine_similarity(novo_descritivo_embedding, embedding_atual)
                if sim > 0.85:
                    logger.info(f"[ContextoService] Atualizao ignorada: Similaridade de cosseno {sim:.4f} > 0.85 (A IA j conhece este padro para a conta {conta_codigo}).")
                    return
                else:
                    logger.info(f"[ContextoService] Contexto precisa ser atualizado para a conta {conta_codigo}: similaridade={sim:.4f} <= 0.85.")
            
            # Se nao existir ou se for <= 0.85
            if contexto_atual:
                prompt = (
                    f"Incorpore os detalhes desta nova despesa/historico: '{novo_descritivo}' "
                    f"ao contexto geral desta conta contabil: '{contexto_atual}'. "
                    f"Sintetize um texto explicativo da finalidade contabil, escopo da conta e exemplos tipicos de despesa. "
                    f"O texto DEVE ter entre 250 e 350 caracteres. Retorne apenas o novo contexto consolidado, sem introducoes."
                )
            else:
                prompt = (
                    f"Sintetize uma definicao inicial de contexto para a conta contabil descrita por '{conta_descricao}' "
                    f"baseada no seguinte historico/despesa: '{novo_descritivo}'. "
                    f"Sintetize um texto explicativo da finalidade contabil, escopo da conta e exemplos tipicos de despesa. "
                    f"O texto DEVE ter entre 250 e 350 caracteres. Retorne apenas o contexto sintetizado, sem introducoes."
                )

            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt],
                config=types.GenerateContentConfig(temperature=0.0)
            )
            novo_contexto = resp.text.strip()

            # Gera o novo embedding usando a regra da Ancoragem de Titulo
            texto_ancoragem = f"{conta_descricao} - {novo_contexto}"
            emb_res = client.models.embed_content(
                model="gemini-embedding-2",
                contents=texto_ancoragem,
                config=types.EmbedContentConfig(output_dimensionality=768)
            )
            novo_embedding = emb_res.embeddings[0].values

            # Atualiza no Supabase
            supabase.table("plano_contas").update({
                "contexto": novo_contexto,
                "embedding": list(novo_embedding),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("administradora_id", str(admin_id)).eq("codigo", conta_codigo).execute()

            logger.info(f"[ContextoService] Contexto atualizado com sucesso para a conta {conta_codigo}.")
        except Exception as e:
            logger.error(f"[ContextoService] Erro ao atualizar contexto da conta {conta_codigo}: {e}")
