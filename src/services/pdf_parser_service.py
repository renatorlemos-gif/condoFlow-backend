import logging
import re
import pymupdf

logger = logging.getLogger(__name__)

async def extract_balancete_data(pdf_bytes: bytes) -> list:
    """
    Extrai texto do PDF localmente com PyMuPDF e extrai dados usando Expressões Regulares,
    eliminando a dependência do Gemini para otimizar tokens e performance.
    Retorna lista de dicts com (descricao_lancamento, conta_codigo, conta_descricao).
    """
    logger.info(f"Tamanho do PDF: {len(pdf_bytes)} bytes")
    if not pdf_bytes:
        raise ValueError("Arquivo PDF vazio (0 bytes recebidos).")

    # Extrai texto do PDF com PyMuPDF
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    texto_pdf = ""
    for page in doc:
        texto_pdf += page.get_text()
    doc.close()

    if not texto_pdf.strip():
        raise ValueError("Não foi possível extrair texto do PDF. O arquivo pode ser uma imagem escaneada.")

    resultados = []
    
    # Achatar o texto para evitar problemas de quebra de bloco/coluna
    texto_pdf_flat = re.sub(r'\s+', ' ', texto_pdf)
    
    if "DESPESAS" in texto_pdf_flat:
        texto_pdf_flat = texto_pdf_flat.split("DESPESAS", 1)[-1]
        
    with open('/tmp/dump.txt', 'w', encoding='utf-8') as f_dump:
        f_dump.write(texto_pdf_flat)
    
    # Regex permissiva ancorada no valor monetário
    padrao = re.compile(r'([\d.]+\,\d{2})\s+([A-Za-zÀ-ÿ\s/.-]+?)\s+(\d{2}/\d{4})\s+(\d{3})\s+(.*?)(?=\s+[\d.]+\,\d{2}\s+[A-Za-zÀ-ÿ]|$)')

    for match in padrao.finditer(texto_pdf_flat):
        resultados.append({
            "descricao_lancamento": match.group(5).strip(),
            "conta_codigo": match.group(4),
            "conta_descricao": match.group(2).strip()
        })

    return resultados
