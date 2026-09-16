import os
import json
import logging
import asyncio
import pymupdf
from google import genai

logger = logging.getLogger(__name__)

async def extract_balancete_data(pdf_bytes: bytes) -> list:
    """
    Extrai texto do PDF localmente com PyMuPDF e envia para o Gemini
    como texto puro, evitando dependência de modelos multimodais.
    Retorna lista de dicts com (fornecedor_nome, conta_codigo, valor_referencia).
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY não configurada")
        raise ValueError("GEMINI_API_KEY ausente.")

    logger.info(f"Tamanho do PDF: {len(pdf_bytes)} bytes")
    if not pdf_bytes:
        raise ValueError("Arquivo PDF vazio (0 bytes recebidos).")

    # 1. Extrai texto do PDF com PyMuPDF (local, sem custo de API)
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    texto_pdf = ""
    for page in doc:
        texto_pdf += page.get_text()
    doc.close()

    if not texto_pdf.strip():
        raise ValueError("Não foi possível extrair texto do PDF. O arquivo pode ser uma imagem escaneada.")

    client = genai.Client(api_key=api_key)

    prompt = f"""Analise o texto abaixo extraído de um balancete contábil de condomínio.
Extraia APENAS as linhas de despesas/pagamentos realizados.
Ignore: receitas, saldos, totais consolidados, cabeçalhos e rodapés.
O formato de saída DEVE ser estritamente um array JSON sem formatação Markdown.
Cada objeto deve ter:
- "fornecedor_nome" (string): nome do fornecedor ou descrição da despesa
- "conta_codigo" (string ou null): código contábil, se presente (ex: "3.1.01.01")
- "conta_descricao" (string ou null): descrição textual da conta contábil (ex: "Despesas com Água", "Manutenção Predial")
- "valor_referencia" (float): valor numérico da despesa (use ponto como separador decimal)
Exemplo: [{{"fornecedor_nome": "Sabesp", "conta_codigo": "3.2.01", "conta_descricao": "Despesas com Água e Esgoto", "valor_referencia": 1500.00}}]

TEXTO DO BALANCETE:
{texto_pdf}
"""

    def _process():
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt
        )
        return response.text

    try:
        text = await asyncio.to_thread(_process)

        # Limpar possíveis delimitadores de markdown
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = json.loads(text)
        if not isinstance(data, list):
            data = [data]
        return data

    except Exception as e:
        logger.error(f"Erro no pdf_parser_service: {e}")
        raise e
