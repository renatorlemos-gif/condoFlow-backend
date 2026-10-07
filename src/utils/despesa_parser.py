import hashlib
import os
import re
import asyncio
import random

from fastapi import UploadFile
import pydantic
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.genai.errors import APIError


class DadosExtraidosDTO(BaseModel):
    cnpj_cpf_fornecedor: str | None = Field(default=None, description="CNPJ ou CPF do fornecedor")
    nome_fornecedor: str | None = Field(default=None, description="Razão Social ou Nome Fantasia")
    numero_despesa: str | None = Field(default=None, description="Número da Nota Fiscal ou Recibo")
    data_emissao: str | None = Field(default=None, description="Data no formato YYYY-MM-DD")
    data_vencimento: str | None = Field(default=None, description="Data no formato YYYY-MM-DD")
    data_pagamento: str | None = Field(default=None, description="Data no formato YYYY-MM-DD")
    valor_total: float | None = Field(default=None, description="Valor monetário total, já convertido para float")
    descricao: str | None = Field(default=None, description="Descrição dos serviços/produtos")
    contexto_sintetizado: str | None = Field(default=None, description="Definição contábil do serviço/produto, preservando termos técnicos")
    chave_acesso: str | None = Field(default=None, description="Chave de Acesso (44 ou 50 dígitos)")
    competencia: str | None = Field(default=None, description="Competência no formato MM/YYYY")

class _ExtracaoBrutaSchema(BaseModel):
    """Formato que o Gemini retorna. valor_total_bruto fica como string,
    exatamente como impresso no despesa — a conversão para float é feita
    em Python (parse_valor_brl), não pelo modelo."""

    cnpj_cpf_fornecedor: str | None = None
    nome_fornecedor: str | None = None
    numero_despesa: str | None = None
    data_emissao: str | None = None
    data_vencimento: str | None = None
    data_pagamento: str | None = None
    valor_total_bruto: str | None = None
    descricao: str | None = None
    contexto_sintetizado: str | None = None
    chave_acesso: str | None = None
    competencia: str | None = None

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


class DespesaParser:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não foi encontrada nas variáveis de ambiente.")

        self.client = genai.Client(api_key=api_key)

    def calcular_hash(self, file_bytes: bytes) -> str:
        return hashlib.sha256(file_bytes).hexdigest()

    async def parse_despesa(self, file: UploadFile) -> tuple[DadosExtraidosDTO, str]:
        contents = await file.read()
        hash_arquivo = self.calcular_hash(contents)

        prompt = """Você é um especialista contábil brasileiro. Extraia os dados desta
despesa fiscal (nota fiscal, recibo, folha de pagamento, fatura) seguindo estas regras
com atenção:

- REGRA 1 (PREVALÊNCIA DE PAGAMENTO - REGIME DE CAIXA): O condomínio opera sob Regime de Caixa. QUALQUER comprovação de pagamento (Pix, TED, recibo assinado, boleto quitado, CUPOM FISCAL) PREVALECE SEMPRE sobre a Nota Fiscal para data ('data_pagamento') e valor ('valor_total_bruto'). A Nota Fiscal só é usada para data e valor em último caso absoluto, quando não houver NENHUMA comprovação de pagamento no arquivo.
- valor_total_bruto: o VALOR TOTAL A PAGAR efetivamente desembolsado. Retorne EXATAMENTE como impresso (ex: "105.900,00"), sem converter ou fazer contas. NÃO confunda com valor unitário, total de item, "valor total dos produtos", bases/impostos ICMS/IPI/ISS (aplicável quando cair no fallback da NF).
- Datas sempre no formato YYYY-MM-DD.
- Campos que não aparecerem devem ficar nulos, não invente valores.
- nome_fornecedor: Retorne em padrão Title Case (Nomes Próprios com iniciais maiúsculas), preposições em minúsculas e siglas empresariais/fiscais preservadas em maiúsculas (ex: LTDA, S/A, ME, PIX). NUNCA retorne em caixa alta integral.
- contexto_sintetizado: Remova nomes próprios/números, PRESERVE termos técnicos e o núcleo do serviço prestado (ex: Autovistoria, Material Elétrico). O texto NUNCA deve ser em caixa alta.
- descricao: Escreva em português, padrão Sentence Case (Capitalização normal de sentença, só a primeira letra maiúscula), NUNCA em caixa alta integral. Siga ESTRITAMENTE estas formatações:
  (1) Salários/Trabalhistas: "{Tipo} {Nome Completo do Funcionário}".
  (2) Fiscais/PJ: "{Fornecedor} {Tipo (NF, etc)} {Número}".
  (3) Serviços/PF: "{Nome da pessoa} ref. {descrição resumida}".
  (4) Parcelamentos: Adicione " - parcela X/Y" se aplicável.
- chave_acesso: Procurar em TODAS as páginas, apenas os 44 ou 50 dígitos numéricos. null se não existir.
- REGRA 9 (COMPETÊNCIA): Formato MM/YYYY. Faça uma BUSCA EXAUSTIVA por menções expressas da data/período de execução do serviço ou compra no corpo do texto (ex: "ref. ao mês de", "competência"). Apenas se não encontrar, use a data de emissão. E como último recurso absoluto, a data de pagamento. NUNCA DEVE FICAR NULA.
- REGRA 10 (FORNECEDOR PF/TRABALHISTA E CONDOMÍNIO): O fornecedor é sempre quem prestou o serviço/vendeu o produto. Em recibos de salários, férias, adiantamentos ou prestadores pessoa física, o 'nome_fornecedor' é SEMPRE o nome completo da pessoa física (funcionário/prestador) e o CPF vai em 'cnpj_cpf_fornecedor'. O Condomínio pagador É TERMINANTEMENTE PROIBIDO de constar como fornecedor. Se não houver número fiscal explícito, 'numero_despesa' deve ser null."""

        response_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "cnpj_cpf_fornecedor": types.Schema(type=types.Type.STRING, description="CNPJ ou CPF do fornecedor"),
                "nome_fornecedor": types.Schema(
                    type=types.Type.STRING, 
                    description="Razão Social ou Nome Fantasia. Quando funcionário/prestador PF, usar o nome completo. OBRIGATÓRIO: Title Case, NUNCA caixa alta."
                ),
                "numero_despesa": types.Schema(type=types.Type.STRING, description="Número da Nota Fiscal ou Recibo"),
                "data_emissao": types.Schema(type=types.Type.STRING, description="Data no formato YYYY-MM-DD"),
                "data_vencimento": types.Schema(type=types.Type.STRING, description="Data no formato YYYY-MM-DD"),
                "data_pagamento": types.Schema(type=types.Type.STRING, description="Data no formato YYYY-MM-DD"),
                "valor_total_bruto": types.Schema(
                    type=types.Type.STRING,
                    description="Valor efetivamente pago conforme comprovação de pagamento; NF apenas se não houver comprovação",
                ),
                "descricao": types.Schema(type=types.Type.STRING, description="Descrição dos serviços/produtos em Sentence Case. NUNCA caixa alta."),
                "contexto_sintetizado": types.Schema(
                    type=types.Type.STRING,
                    description="Definição contábil do serviço/produto, sem caixa alta",
                ),
                "chave_acesso": types.Schema(
                    type=types.Type.STRING,
                    description="Chave de Acesso da nota fiscal, contendo apenas os 44 ou 50 dígitos numéricos",
                    nullable=True,
                ),
                "competencia": types.Schema(
                    type=types.Type.STRING,
                    description="Competência contábil no formato MM/YYYY. OBRIGATÓRIO: se omisso, deduza pelo pagamento/emissão.",
                ),
            },
        )

        model_primary = os.environ.get("GEMINI_MODEL_PRIMARY", "gemini-3.1-flash-lite")
        model_fallback = os.environ.get("GEMINI_MODEL_FALLBACK", "gemini-3.8-flash")
        
        modelo_atual = model_primary
        max_tentativas = 4
        tentativas_qualitativas = 0
        bruto = None

        for attempt in range(1, max_tentativas + 1):
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=modelo_atual,
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
                        temperature=0,
                    ),
                )
                
                bruto = _ExtracaoBrutaSchema.model_validate_json(response.text)
                
                valor_processado_tmp = parse_valor_brl(bruto.valor_total_bruto)
                
                if valor_processado_tmp is None or not bruto.competencia or bruto.competencia.strip() == "":
                    if tentativas_qualitativas == 0 and modelo_atual == model_primary:
                        modelo_atual = model_fallback
                        tentativas_qualitativas += 1
                        continue
                        
                break
                
            except Exception as e:
                if isinstance(e, pydantic.ValidationError):
                    if tentativas_qualitativas == 0 and modelo_atual == model_primary:
                        modelo_atual = model_fallback
                        tentativas_qualitativas += 1
                        continue
                    else:
                        if attempt == max_tentativas:
                            raise Exception(f"Falha qualitativa após escalonamento: {e}")
                        continue
                
                if attempt == max_tentativas:
                    raise e
                
                if isinstance(e, APIError):
                    if e.code == 429:
                        is_rpd = False
                        if e.details:
                            for detail in e.details:
                                detail_str = str(detail).lower()
                                if "perday" in detail_str or "per_day" in detail_str:
                                    is_rpd = True
                                    break
                                    
                        if is_rpd:
                            modelo_atual = model_fallback
                            continue
                        else:
                            delay = 30 + random.uniform(0, 30)
                            if e.details:
                                for detail in e.details:
                                    if "retryDelay" in detail:
                                        try:
                                            rd = detail["retryDelay"]
                                            if isinstance(rd, str) and rd.endswith('s'):
                                                delay = float(rd[:-1])
                                            elif isinstance(rd, (int, float)):
                                                delay = float(rd)
                                        except Exception:
                                            pass
                            await asyncio.sleep(delay)
                    elif "503" in str(e):
                        delay = 30 + random.uniform(0, 30)
                        await asyncio.sleep(delay)
                    else:
                        # Para outros erros de rede (ex: SSL drop, httpx.ReadError), tenta mais uma vez
                        if attempt < max_tentativas:
                            await asyncio.sleep(2)
                        else:
                            raise e
                else:
                    raise e

        if bruto is None:
            raise Exception("Falha na extração de dados: retorno nulo.")

        valor_processado = parse_valor_brl(bruto.valor_total_bruto) or 0.0

        comp = bruto.competencia
        if not comp or comp.strip() == "":
            fallback_date = bruto.data_pagamento or bruto.data_emissao or bruto.data_vencimento
            if fallback_date and len(fallback_date) >= 7:
                parts = fallback_date.split("-")
                if len(parts) >= 2:
                    comp = f"{parts[1]}/{parts[0]}"

        from src.utils.text_sanitizer import sanitize_nome_fornecedor, sanitize_descricao
        
        dados_extraidos = DadosExtraidosDTO(
            cnpj_cpf_fornecedor=bruto.cnpj_cpf_fornecedor,
            nome_fornecedor=sanitize_nome_fornecedor(bruto.nome_fornecedor),
            numero_despesa=bruto.numero_despesa,
            data_emissao=bruto.data_emissao,
            data_vencimento=bruto.data_vencimento,
            data_pagamento=bruto.data_pagamento,
            valor_total=valor_processado,
            descricao=sanitize_descricao(bruto.descricao),
            contexto_sintetizado=sanitize_descricao(bruto.contexto_sintetizado),
            chave_acesso=bruto.chave_acesso,
            competencia=comp,
        )

        return dados_extraidos, hash_arquivo
