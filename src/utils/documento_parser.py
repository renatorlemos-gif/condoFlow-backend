import hashlib
import os
import re

from fastapi import UploadFile
from pydantic import BaseModel, Field
from google import genai
from google.genai import types


class DadosExtraidosDTO(BaseModel):
    cnpj_cpf_fornecedor: str | None = Field(
        default=None,
        description="CNPJ ou CPF do fornecedor"
    )

    nome_fornecedor: str | None = Field(
        default=None,
        description="Razão Social ou Nome Fantasia"
    )

    numero_documento: str | None = Field(
        default=None,
        description="Número da Nota Fiscal ou Recibo"
    )

    data_emissao: str | None = Field(
        default=None,
        description="Data no formato YYYY-MM-DD"
    )

    data_vencimento: str | None = Field(
        default=None,
        description="Data no formato YYYY-MM-DD"
    )

    data_pagamento: str | None = Field(
        default=None,
        description="Data no formato YYYY-MM-DD"
    )

    valor_total: float | None = Field(
        default=None,
        description="Valor monetário total, já convertido para float"
    )

    descricao: str | None = Field(
        default=None,
        description="Descrição dos serviços/produtos"
    )


class _ExtracaoBrutaSchema(BaseModel):
    """
    Formato que o Gemini retorna.

    valor_total_bruto fica como string, exatamente como
    impresso no documento. A conversão para float é feita
    em Python.
    """

    cnpj_cpf_fornecedor: str | None = None
    nome_fornecedor: str | None = None
    numero_documento: str | None = None
    data_emissao: str | None = None
    data_vencimento: str | None = None
    data_pagamento: str | None = None
    valor_total_bruto: str | None = None
    descricao: str | None = None


def parse_valor_brl(valor_str: str | None) -> float | None:
    """
    Converte um valor no formato brasileiro.

    Exemplos:

    'R$ 105.900,00' -> 105900.00
    '105.900,00'    -> 105900.00
    '900,00'        -> 900.00
    """

    if not valor_str:
        return None

    limpo = re.sub(r"[^\d,.\-]", "", valor_str).strip()

    if not limpo:
        return None

    tem_virgula = "," in limpo
    tem_ponto = "." in limpo

    if tem_virgula and tem_ponto:
        # Exemplo:
        # 105.900,00
        # vira:
        # 105900.00
        limpo = limpo.replace(".", "").replace(",", ".")

    elif tem_virgula:
        # Exemplo:
        # 900,00
        # vira:
        # 900.00
        limpo = limpo.replace(",", ".")

    try:
        return float(limpo)

    except ValueError:
        return None


class DocumentoParser:

    def __init__(self):

        # ============================================================
        # 1. LÊ A API KEY DO AMBIENTE
        # ============================================================

        api_key = os.environ.get("GEMINI_API_KEY")

        # ============================================================
        # 2. DIAGNÓSTICO DO AMBIENTE
        # ============================================================

        print("")
        print("==================================================")
        print("DIAGNÓSTICO GEMINI - INÍCIO")
        print("==================================================")

        # Não imprime a chave inteira por segurança.
        print(
            "GEMINI_API_KEY presente:",
            bool(api_key)
        )

        print(
            "GEMINI_API_KEY tamanho:",
            len(api_key) if api_key else 0
        )

        if api_key:
            print(
                "GEMINI_API_KEY prefixo:",
                api_key[:8]
            )
        else:
            print(
                "GEMINI_API_KEY prefixo: None"
            )

        # ============================================================
        # 3. VERIFICA POSSÍVEIS CONFLITOS DE AUTENTICAÇÃO
        # ============================================================

        google_api_key = os.environ.get("GOOGLE_API_KEY")

        google_application_credentials = os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )

        google_genai_use_enterprise = os.environ.get(
            "GOOGLE_GENAI_USE_ENTERPRISE"
        )

        google_cloud_project = os.environ.get(
            "GOOGLE_CLOUD_PROJECT"
        )

        google_cloud_location = os.environ.get(
            "GOOGLE_CLOUD_LOCATION"
        )

        print(
            "GOOGLE_API_KEY presente:",
            bool(google_api_key)
        )

        print(
            "GOOGLE_APPLICATION_CREDENTIALS presente:",
            bool(google_application_credentials)
        )

        print(
            "GOOGLE_GENAI_USE_ENTERPRISE:",
            google_genai_use_enterprise
        )

        print(
            "GOOGLE_CLOUD_PROJECT:",
            google_cloud_project
        )

        print(
            "GOOGLE_CLOUD_LOCATION:",
            google_cloud_location
        )

        print("==================================================")

        # ============================================================
        # 4. VALIDA SE A GEMINI_API_KEY EXISTE
        # ============================================================

        if not api_key:

            print(
                "ERRO: GEMINI_API_KEY não encontrada."
            )

            print("==================================================")

            raise RuntimeError(
                "GEMINI_API_KEY não foi encontrada "
                "nas variáveis de ambiente."
            )

        # ============================================================
        # 5. CRIA O CLIENTE GEMINI EXPLICITAMENTE COM API KEY
        # ============================================================

        print(
            "Criando cliente Gemini usando GEMINI_API_KEY..."
        )

        self.client = genai.Client(
            api_key=api_key
        )

        print(
            "Cliente Gemini criado."
        )

        # ============================================================
        # 6. TESTE REAL DA AUTENTICAÇÃO
        # ============================================================

        print("")
        print(
            "Executando teste de autenticação Gemini..."
        )

        try:

            teste_response = self.client.models.generate_content(
                model="gemini-3.6-flash",
                contents="Responda apenas com a palavra OK."
            )

            print(
                "TESTE GEMINI: SUCESSO"
            )

            print(
                "Resposta:",
                teste_response.text
            )

        except Exception as e:

            print("")
            print("==================================================")
            print("TESTE GEMINI: FALHOU")
            print("==================================================")

            print(
                "Tipo do erro:",
                type(e).__name__
            )

            print(
                "Mensagem:",
                str(e)
            )

            print("==================================================")

            # Interrompe a inicialização.
            #
            # Isso é proposital neste momento:
            # se a autenticação não funciona, não faz
            # sentido continuar tentando processar documentos.

            raise

        print("==================================================")
        print("DIAGNÓSTICO GEMINI - FIM")
        print("==================================================")
        print("")

    # ================================================================
    # HASH DO ARQUIVO
    # ================================================================

    def calcular_hash(self, file_bytes: bytes) -> str:

        return hashlib.sha256(file_bytes).hexdigest()

    # ================================================================
    # PROCESSAMENTO DO DOCUMENTO
    # ================================================================

    async def parse_documento(
        self,
        file: UploadFile
    ) -> tuple[DadosExtraidosDTO, str]:

        contents = await file.read()

        hash_arquivo = self.calcular_hash(
            contents
        )

        # ============================================================
        # PROMPT
        # ============================================================

        prompt = """
Você é um especialista contábil brasileiro. Extraia os dados deste
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
  valores.
"""

        # ============================================================
        # SCHEMA DA RESPOSTA
        # ============================================================

        response_schema = types.Schema(
            type=types.Type.OBJECT,

            properties={

                "cnpj_cpf_fornecedor": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "CNPJ ou CPF do fornecedor"
                    )
                ),

                "nome_fornecedor": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Razão Social ou Nome Fantasia"
                    )
                ),

                "numero_documento": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Número da Nota Fiscal ou Recibo"
                    )
                ),

                "data_emissao": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Data no formato YYYY-MM-DD"
                    )
                ),

                "data_vencimento": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Data no formato YYYY-MM-DD"
                    )
                ),

                "data_pagamento": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Data no formato YYYY-MM-DD"
                    )
                ),

                "valor_total_bruto": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Valor total da nota, exatamente "
                        "como impresso, com pontuação original "
                        "(ex: '105.900,00')"
                    ),
                ),

                "descricao": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Descrição dos serviços/produtos"
                    )
                ),
            },
        )

        # ============================================================
        # CHAMADA AO GEMINI PARA O DOCUMENTO
        # ============================================================

        response = self.client.models.generate_content(

            model="gemini-3.6-flash",

            contents=[

                types.Part.from_bytes(
                    data=contents,
                    mime_type=(
                        file.content_type
                        or "application/pdf"
                    ),
                ),

                prompt,
            ],

            config=types.GenerateContentConfig(

                response_mime_type="application/json",

                response_schema=response_schema,

                temperature=0,
            ),
        )

        # ============================================================
        # CONVERTE RESPOSTA DO GEMINI
        # ============================================================

        bruto = _ExtracaoBrutaSchema.model_validate_json(
            response.text
        )

        # ============================================================
        # MONTA DTO FINAL
        # ============================================================

        dados_extraidos = DadosExtraidosDTO(

            cnpj_cpf_fornecedor=(
                bruto.cnpj_cpf_fornecedor
            ),

            nome_fornecedor=(
                bruto.nome_fornecedor
            ),

            numero_documento=(
                bruto.numero_documento
            ),

            data_emissao=(
                bruto.data_emissao
            ),

            data_vencimento=(
                bruto.data_vencimento
            ),

            data_pagamento=(
                bruto.data_pagamento
            ),

            valor_total=(
                parse_valor_brl(
                    bruto.valor_total_bruto
                ) or 0.0
            ),

            descricao=(
                bruto.descricao
            ),
        )

        return dados_extraidos, hash_arquivo