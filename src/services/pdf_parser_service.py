import os
import json
import logging
import asyncio
from google import genai

logger = logging.getLogger(__name__)

async def extract_balancete_data(pdf_bytes: bytes) -> list:
    """
    Usa o Gemini para extrair (fornecedor_nome, conta_codigo, valor_referencia)
    de um PDF de balancete. Retorna uma lista de dicts.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY não configurada")
        raise ValueError("GEMINI_API_KEY ausente.")

    client = genai.Client(api_key=api_key)
    
    import tempfile
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        def _process():
            uploaded_file = client.files.upload(file=tmp_path, config={'mime_type': 'application/pdf'})
            
            prompt = """
            Analise este PDF de balancete e extraia as despesas/pagamentos em uma lista JSON.
            Ignore outras informações, como receitas, totais e saldos bancários, se houver.
            O formato de saída DEVE ser estritamente um array JSON sem formatação Markdown nem texto adicional.
            Cada objeto do array deve ter as chaves "fornecedor_nome" (string), "conta_codigo" (string ou null) e "valor_referencia" (float).
            Exemplo:
            [
              {"fornecedor_nome": "Sabesp", "conta_codigo": "1.2.3", "valor_referencia": 1500.00}
            ]
            """
            
            response = client.models.generate_content(
                model='gemini-3.5-flash-lite',
                contents=[uploaded_file, prompt]
            )
            return response.text

        text = await asyncio.to_thread(_process)
        
        # Limpar possiveis delimitadores de markdown (```json e ```)
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
    finally:
        os.remove(tmp_path)
