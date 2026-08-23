import hashlib
import os
import re

from fastapi import UploadFile
from pydantic import BaseModel, Field
from google import genai
from google.genai import types


class DadosExtraidosDTO(BaseModel):
    cnpj_cpf_fornecedor: str | None = Field(default=None, description="CNPJ ou CPF do fornecedor")
    nome_fornecedor: str | None = Field(default=None, description="Razão Social ou Nome Fantasia")
    numero_documento: str | None = Field(default=None, description="Número da Nota Fiscal ou Recibo")
    data_emissao: str | None = Field(default=None, description="Data no formato YYYY-MM-DD")
    data_vencimento: str | None = Field(default=None, description="Data no formato YYYY-MM-DD")
    data_pagamento: str | None = Field(default=None, description="Data no formato YYYY-MM-DD")
    valor_total: float | None = Field(default=None, description="Valor monetário total, já convertido para float")
    descricao: str | None = Field(default=None, description="Descrição dos serviços/produtos")


class _ExtracaoBrutaSchema(BaseModel):
    """Formato que o Gemini retorna. valor_total_bruto fica como string,
    exatamente como impresso no documento — a conversão para float é feita
    em Python (parse_valor_brl), não pelo modelo. LLM não é confiável para
    fazer conta / conversão numérica de forma determinística."""

    cnpj_cpf_fornecedor: str | None = None
    nome_fornecedor: str | None = None
    numero_documento: str | None = None
    data_emissao: str | None = None
    data_vencimento: str | None = None
    data_pagamento: str | None = None
    valor_total_bruto: str | None = None
    descricao: str | None = None


def parse_valor_brl(valor_str: str | None) -> float | None:
    """Converte um valor no formato brasileiro (ex: 'R$ 105.900,00' ou
    '105.900,00') para float (105900.00). Retorna None se não conseguir
    interpretar."""
    if not valor_str:
        return None

    limpo = re.sub(r"[^\d,.\-]", "", valor_str).strip()
    if not limpo:
        return None

    tem_virgula = "," in limpo
    tem_ponto = "." in limpo

    if tem_virgula and tem_ponto:
        # padrão BR: ponto de milhar, vírgula decimal -> "105.900,00"
        limpo = limpo.replace(".", "").replace(",", ".")
    elif tem_virgula:
        # só vírgula -> é o separador decimal -> "900,00"
        limpo = limpo.replace(",", ".")
    # só ponto (ou nenhum separador) já está em formato válido para float

    try:
        return float(limpo)
    except ValueError:
        return None


class DocumentoParser:
    def __init__(self):
        # Força o uso explícito da API Key do ambiente para evitar conflitos com credenciais do Google Cloud
        api_key = os.environ.get("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key)

    def calcular_hash(self, file_bytes: bytes) -> str:
        return hashlib.sha256(file_bytes).hexdigest()

    async def parse_documento(self, file: UploadFile) -> tuple[DadosExtraidosDTO, str]:
        contents = await file.read()
        hash_arquivo = self.calcular_hash(contents)

        prompt = """Você é um especialista contábil brasileiro. Extraia os dados deste
documento fiscal (nota fiscal, recibo ou fatura) seguindo estas regras
com atenção:

- valor_total_bruto: o VALOR TOTAL A PAGAR do documento — normalmente o
  campo "VALOR TOTAL DA NOTA", "VALOR TOTAL DO DOCUMENTO" ou equivalente.
  NÃO confunda com "VALOR UNITÁRIO", "V. TOTAL" de um item específico,
  "VALOR TOTAL DOS PRODUTOS" (quando houver frete/desconto/impostos que
  mudem o total), base de cálculo de impostos ou valores de ICMS/IPI/ISS.
  Se houver dúvida entre "valor total dos produtos" e "valor total da
  nota", prefira sempre "valor total da nota" (o que o destinatário
  efetivamente paga).
- Retorne valor_total_bruto EXATAMENTE como está impresso no documento,
  incluindo a pontuação original brasileira (ex: "105.900,00"). NÃO
  converta, NÃO faça nenhuma conta — apenas copie o texto do valor.
- Datas sempre no formato YYYY-MM-DD.
- Campos que não aparecerem no documento devem ficar nulos, não invente
  valores."""

        response_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "cnpj_cpf_fornecedor": types.Schema(type=types.Type.STRING, description="CNPJ ou CPF do fornecedor"),
                "nome_fornecedor": types.Schema(type=types.Type.STRING, description="Razão Social ou Nome Fantasia"),
                "numero_documento": types.Schema(type=types.Type.STRING, description="Número da Nota Fiscal ou Recibo"),
                "data_emissao": types.Schema(type=types.Type.STRING, description="Data no formato YYYY-MM-DD"),
                "data_vencimento": types.Schema(type=types.Type.STRING, description="Data no formato YYYY-MM-DD"),
                "data_pagamento": types.Schema(type=types.Type.STRING, description="Data no formato YYYY-MM-DD"),
                "valor_total_bruto": types.Schema(
                    type=types.Type.STRING,
                    description="Valor total da nota, exatamente como impresso, com pontuação original (ex: '105.900,00')",
                ),
                "descricao": types.Schema(type=types.Type.STRING, description="Descrição dos serviços/produtos"),
            },
        )

        response = self.client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[
                types.Part.from_bytes(
                    data=contents,
                    mime_type=file.content_type or "application/pdf",
                ),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0,  # determinístico — mesma nota deve sempre extrair o mesmo valor
            ),
        )

        bruto = _ExtracaoBrutaSchema.model_validate_json(response.text)

        dados_extraidos = DadosExtraidosDTO(
            cnpj_cpf_fornecedor=bruto.cnpj_cpf_fornecedor,
            nome_fornecedor=bruto.nome_fornecedor,
            numero_documento=bruto.numero_documento,
            data_emissao=bruto.data_emissao,
            data_vencimento=bruto.data_vencimento,
            data_pagamento=bruto.data_pagamento,
            valor_total=parse_valor_brl(bruto.valor_total_bruto) or 0.0,
            descricao=bruto.descricao,
        )

        return dados_extraidos, hash_arquivo