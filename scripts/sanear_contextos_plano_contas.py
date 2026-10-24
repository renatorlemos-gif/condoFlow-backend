#!/usr/bin/env python3
"""
Script CLI de Saneamento e Re-vetorização Retroativa no Supabase (v1.53).
Saneia contextos prolixos (> 140 chars) e re-vetoriza com Ancoragem de Título no pgvector.
"""

import os
import sys
import time
import asyncio
import argparse
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from google import genai
from google.genai import types
from google.genai.errors import APIError
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sanear_contextos")


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Saneamento retroativo e re-vetorizacao de contextos do plano de contas (v1.53)."
    )
    parser.add_argument(
        "--administradora-id",
        "-a",
        type=str,
        default=None,
        help="UUID da administradora para filtrar (opcional; padrao: todas as administradoras)."
    )
    parser.add_argument(
        "--limite-chars",
        "-l",
        type=int,
        default=140,
        help="Limite de caracteres a partir do qual o contexto e considerado prolixo (padrao: 140)."
    )
    parser.add_argument(
        "--todas",
        action="store_true",
        help="Forca o saneamento e re-vetorizacao de todas as contas com contexto, ignorando o limite de caracteres."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Modo de simulacao: lista contas elegiveis sem chamar a IA ou alterar o banco."
    )
    return parser.parse_args(args)


class SaneadorContextos:
    def __init__(self, supabase_client: Client, gemini_client: Optional[genai.Client] = None):
        self.supabase = supabase_client
        self.gemini = gemini_client

    async def sintetizar_e_vetorizar_com_backoff(
        self,
        descricao: str,
        contexto_antigo: str,
        max_retries: int = 3
    ) -> tuple[str, List[float]]:
        prompt = (
            f"Sintetize e condense o seguinte contexto da conta contabil '{descricao}':\n"
            f"'{contexto_antigo}'\n\n"
            f"Diretrizes:\n"
            f"1. O texto resultante DEVE ter estritamente entre 80 e 140 caracteres em 1 ou 2 frases curtas.\n"
            f"2. Descreva apenas o nucleo da finalidade contabil e o escopo da conta.\n"
            f"3. PROIBICAO TAXATIVA: E terminantemente proibido utilizar termos genericos e abrangentes como 'despesas operacionais gerais', 'servicos diversos', 'manutencao predial ampla', 'gastos rotineiros' ou 'taxas administrativas'.\n"
            f"4. NUNCA inclua nomes proprios de pessoas ou funcionarios, numeros de documentos, pedidos, notas fiscais ou datas.\n"
            f"Retorne apenas o contexto condensado, sem introducoes."
        )

        delays = [5.0, 10.0, 20.0]
        last_error = None

        for attempt in range(max_retries):
            try:
                # 1. Gerar novo contexto condensado
                resp = self.gemini.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=[prompt],
                    config=types.GenerateContentConfig(temperature=0.0)
                )
                novo_contexto = resp.text.strip()

                # 2. Gerar novo embedding com Ancoragem de Título
                texto_ancoragem = f"{descricao} - {novo_contexto}"
                emb_res = self.gemini.models.embed_content(
                    model="gemini-embedding-2",
                    contents=texto_ancoragem,
                    config=types.EmbedContentConfig(output_dimensionality=768)
                )
                novo_embedding = emb_res.embeddings[0].values
                return novo_contexto, novo_embedding

            except Exception as e:
                last_error = e
                # Verifica erro transitório ou rate limit (429, 503)
                is_rate_limit = False
                if isinstance(e, APIError) and getattr(e, "code", None) in (429, 503):
                    is_rate_limit = True
                elif "429" in str(e) or "503" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e):
                    is_rate_limit = True

                if is_rate_limit and attempt < max_retries - 1:
                    wait_time = delays[attempt]
                    logger.warning(
                        f"[RateLimit] Rate limit ou indisponibilidade detectada ({e}). "
                        f"Aplicando backoff de {wait_time}s antes da tentativa {attempt + 2}/{max_retries}..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise e

        raise last_error

    async def executar(
        self,
        administradora_id: Optional[str] = None,
        limite_chars: int = 140,
        todas: bool = False,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        start_time = time.time()
        
        # 1. Consulta contas cadastradas com contexto não nulo
        query = self.supabase.table("plano_contas").select("id, administradora_id, codigo_contabil, descricao, contexto")
        if administradora_id:
            query = query.eq("administradora_id", str(administradora_id))
        
        res = query.execute()
        contas = res.data or []

        total_analisadas = len(contas)
        saneadas = 0
        ignoradas = 0
        erros = 0
        detalhes = []

        logger.info(f"Total de contas recuperadas: {total_analisadas}")
        if dry_run:
            logger.info("=== MODO SIMULACAO (DRY-RUN) ATIVO ===")

        for conta in contas:
            conta_id = conta.get("id")
            codigo = conta.get("codigo_contabil") or "S/C"
            descricao = conta.get("descricao") or "Sem Descricao"
            contexto_atual = conta.get("contexto") or ""
            tam_atual = len(contexto_atual)

            # Verifica elegibilidade
            elegivel = False
            if contexto_atual:
                if todas:
                    elegivel = True
                elif tam_atual > limite_chars:
                    elegivel = True

            if not elegivel:
                ignoradas += 1
                continue

            if dry_run:
                logger.info(f"[DRY-RUN] [Conta {codigo}] '{descricao}' elegivel: {tam_atual} chars (> {limite_chars})")
                saneadas += 1
                detalhes.append({
                    "codigo": codigo,
                    "descricao": descricao,
                    "antes": tam_atual,
                    "depois": None,
                    "status": "simulado"
                })
                continue

            try:
                novo_ctx, novo_emb = await self.sintetizar_e_vetorizar_com_backoff(descricao, contexto_atual)
                tam_novo = len(novo_ctx)

                # Atualizacao atomica no Supabase
                self.supabase.table("plano_contas").update({
                    "contexto": novo_ctx,
                    "embedding": list(novo_emb),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", conta_id).execute()

                logger.info(f"[Conta {codigo}] Saneado: {tam_atual} chars -> {tam_novo} chars")
                saneadas += 1
                detalhes.append({
                    "codigo": codigo,
                    "descricao": descricao,
                    "antes": tam_atual,
                    "depois": tam_novo,
                    "status": "sucesso"
                })

                # Rate limiting preventivo
                await asyncio.sleep(2.0)

            except Exception as err:
                logger.error(f"[Conta {codigo}] Falha no saneamento: {err}")
                erros += 1
                detalhes.append({
                    "codigo": codigo,
                    "descricao": descricao,
                    "antes": tam_atual,
                    "depois": None,
                    "status": f"erro: {err}"
                })

        tempo_total = round(time.time() - start_time, 2)

        relatorio = {
            "total_analisadas": total_analisadas,
            "saneadas": saneadas,
            "ignoradas": ignoradas,
            "erros": erros,
            "tempo_total_segundos": tempo_total,
            "detalhes": detalhes
        }

        # Exibe sumário final
        print("\n" + "=" * 50)
        print("RELATORIO FINAL DE SANEAMENTO DE CONTEXTOS")
        print("=" * 50)
        print(f"Contas Analisadas:  {total_analisadas}")
        print(f"Contas Saneadas:    {saneadas}")
        print(f"Contas Ignoradas:   {ignoradas}")
        print(f"Erros:              {erros}")
        print(f"Tempo Total:        {tempo_total}s")
        print("=" * 50 + "\n")

        return relatorio


async def main():
    args = parse_args()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if not supabase_url or not supabase_key:
        logger.error("Variaveis de ambiente SUPABASE_URL e SUPABASE_SERVICE_KEY sao obrigatorias.")
        sys.exit(1)

    if not args.dry_run and not gemini_key:
        logger.error("Variavel GEMINI_API_KEY e obrigatoria para execucao fora do modo --dry-run.")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)
    gemini_client = genai.Client(api_key=gemini_key) if gemini_key else None

    saneador = SaneadorContextos(supabase, gemini_client)
    await saneador.executar(
        administradora_id=args.administradora_id,
        limite_chars=args.limite_chars,
        todas=args.todas,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    asyncio.run(main())
