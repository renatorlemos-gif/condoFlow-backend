import hashlib
import os
import re
import asyncio
import random
import logging

from fastapi import UploadFile
import pydantic
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger("despesa_parser")


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


def sanitize_chave_acesso(chave: str | None) -> str | None:
    if not chave:
        return None
    digitos = re.sub(r"\D", "", str(chave).strip())
    if len(digitos) == 44:
        return digitos
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

- REGRA 1 (PREVALÊNCIA TOTAL DO COMPROVANTE DE PAGAMENTO - REGIME DE CAIXA):
  (1) PREVALÊNCIA TOTAL DO COMPROVANTE: O condomínio opera sob Regime de Caixa. A 'data_pagamento' e o 'valor_total_bruto' SEMPRE prevalecem pelos dados contidos no COMPROVANTE DE PAGAMENTO (Pix, TED/DOC, transferência entre contas, autenticação mecânica bancária de caixa/agência, boleto quitado, recibo assinado com quitação, débito automático em conta corrente ou comprovante de Internet Banking).
  (2) BUSCA MULTIPÁGINA EXAUSTIVA: O comprovante de pagamento pode estar em QUALQUER página do documento (página 1, página 2, página 3, ou anexo no final do arquivo PDF). Você DEVE examinar TODAS as páginas procurando comprovantes bancários.
  (3) ATENÇÃO CRÍTICA AO ANO: Verifique com extremo rigor o ANO do pagamento no comprovante (ex: pagamentos realizados em 2026 NUNCA devem ser extraídos como 2025).
  (4) NÃO CONFUNDIR COM PERÍODOS DE CONSUMO OU LEITURA: Em faturas de concessionárias (energia elétrica, água/esgoto, gás, telefone/internet), NUNCA use a data de leitura, ciclo de faturamento ou período de apuração/consumo como 'data_pagamento'.
  (5) REGRA DE FALLBACK MANDATÓRIO ESTRITO: Somente quando NÃO HOUVER NENHUM COMPROVANTE DE PAGAMENTO no arquivo, a 'data_pagamento' DEVE ASSUMIR A DATA DE EMISSÃO FISCAL ('data_emissao'). É TERMINANTEMENTE PROIBIDO assumir a data de vencimento ('data_vencimento') ou períodos de uso/faturamento no campo 'data_pagamento'. A data de vencimento é uma previsão futura e não representa pagamento no Regime de Caixa.
- DATA DE EMISSÃO ('data_emissao'): Data oficial de emissão fiscal do documento (data da NF-e, Danfe, NFS-e, cupom fiscal, data do recibo assinado ou data de emissão impressa na fatura). Formato YYYY-MM-DD.
- DATA DE VENCIMENTO ('data_vencimento'): Data limite de vencimento do boleto bancário ou fatura. Formato YYYY-MM-DD. JAMAIS use esta data no campo 'data_pagamento'.
- valor_total_bruto: o VALOR TOTAL A PAGAR efetivamente desembolsado. Retorne EXATAMENTE como impresso (ex: "105.900,00"), sem converter ou fazer contas. NÃO confunda com valor unitário, total de item, "valor total dos produtos", bases/impostos ICMS/IPI/ISS (aplicável quando cair no fallback da NF).
  REGRA MANDATÓRIA PARA DEMONSTRATIVO DE PAGAMENTO / HOLERITE / RECIBO SALARIAL: Em documentos do tipo demonstrativo de pagamento, folha de pagamento, holerite ou recibo (Salários, Adiantamentos, Férias, 13º Salário, Rescisões), o valor procurado DEVE SER OBRIGATORIAMENTE O "VALOR LÍQUIDO" (o valor líquido a receber pelo colaborador). NUNCA utilize o total bruto de proventos, total de descontos ou bases de INSS/FGTS.
- Datas sempre no formato YYYY-MM-DD.
- Campos que não aparecerem devem ficar nulos, não invente valores.
- REGRA CRÍTICA DE ACENTUAÇÃO E ORTOGRAFIA PT-BR: Documentos fiscais e recibos frequentemente omitem acentos e cedilhas por estarem em caixa alta (ex: COMERCIO, GESTAO, SERVICOS, ELETRICA, MANUTENCAO, CONSTRUCAO). Você DEVE OBRIGATORIAMENTE corrigir a grafia de TODAS as palavras para a norma culta com a acentuação correta do Português do Brasil: "Comércio", "Gestão", "Serviços", "Elétrica", "Manutenção", "Construção", "Higienização", "Água", "Gás", etc. NUNCA deixe palavras sem acento ou cedilha em 'nome_fornecedor', 'descricao' e 'contexto_sintetizado'.
- nome_fornecedor: Retorne em padrão Title Case (Nomes Próprios com iniciais maiúsculas), preposições em minúsculas. O nome do fornecedor/prestador/funcionário sempre precisa ser COMPLETO, sem abreviações. Quando fizer parte do nome do fornecedor, a formatação DEVE ser "Ltda" e não "LTDA" ou "LTDA.". Se a empresa for sociedade limitada, a terminação "Ltda" NUNCA PODE SER OMITIDA (ex: "LCM Santos Comércio e Atacadista Ltda"). NUNCA retorne em caixa alta integral. Qualquer nome DEVE vir com acentuação correta pt-BR ("Comércio", "Gestão", "Serviços", "Elétrica", etc) mesmo que o arquivo original não os tenha.
- numero_despesa: Numeração de documentos fiscais deve conter SOMENTE NÚMEROS (remova pontos, traços, barras ou letras).
  (1) Despesas de consumo (energia elétrica, água/esgoto, gás canalizado): busque PRIORITARIAMENTE o número da Nota Fiscal em qualquer rótulo impresso ("NF", "Nº N. Fiscal", "Nota Fiscal", "Doc. Fiscal", "NF3e", "NFS-e", "Danfe"). NUNCA confunda ou utilize número de instalação, número do medidor ou código do cliente. Se e somente se a conta não possuir nenhuma menção a Nota Fiscal, use o número da fatura como fallback secundário.
  (2) Guias de ISS (imposto sobre serviços / ISSQN): busque OBRIGATORIAMENTE o número da guia de recolhimento, considerando rótulos equivalentes como "Nº da Guia", "Nº do DAM" ou "Nº do Documento".
  (3) Demais documentos: número da NF, recibo ou duplicata. null se não existir.
- contexto_sintetizado: Remova nomes próprios/números, PRESERVE termos técnicos e o núcleo do serviço prestado (ex: Autovistoria, Material Elétrico). O texto NUNCA deve ser em caixa alta e DEVE ter acentuação correta pt-BR.
- descricao: Escreva em português, padrão Sentence Case, NUNCA em caixa alta integral. Acentue as palavras OBRIGATORIAMENTE usando padrão pt-BR ("ç", "~", acentos agudos e circunflexos). Elabore um histórico conciso e objetivo, idealmente em até 80 caracteres (mas sem cortar ou mutilar nomes de fornecedores).
  Siga estas diretrizes de composição:
  (1) Fiscais/PJ:
      - SE HOUVER número de documento: "{Fornecedor} {Tipo} {Número}". O tipo de documento deve usar estritamente as grafias "Danfe", "NFSe", "NFe" ou "Doc nº" (NUNCA "DOC nº" em maiúsculo). Em sociedades limitadas, a terminação "Ltda" faz parte do nome e deve constar antes do tipo: "{Fornecedor} Ltda {Tipo} {Número}" (Exemplos: "LCM Santos Comércio Atacadista Ltda Danfe 775", "Casa das Bombas Ltda Danfe 31303", "Cmd Gestão e Serviços Ltda NFSe 15").
      - SE NÃO HOUVER número de documento (numero_despesa for null): retorne APENAS o nome do fornecedor com "Ltda" (se aplicável): "{Fornecedor}". O tipo de documento só deve aparecer se acompanhado do respectivo número.
  (2) Serviços/PF: "{Nome da pessoa} ref. {descrição resumida}".
  (3) Recibos: Quando a despesa for recibo avulso ou prestação de serviços sem nota fiscal, inclua ao final: "conf. recibo" (ex: "{Nome} ref. {serviço} conf. recibo" ou "{Fornecedor} conf. recibo"). NUNCA termine a descrição com ponto final ('.'), exceto se fizer parte de sufixo empresarial como 'S.A.'.
  (4) Parcelamentos: Adicione " - parcela X/Y" se aplicável.
- chave_acesso: Apenas os 44 dígitos numéricos contínuos da Nota Fiscal Eletrônica (NF-e/NFC-e/CT-e), SEM ESPAÇOS e sem pontuação. Se o documento não possuir chave de acesso com 44 dígitos, retorne null.
- REGRA 9 (COMPETÊNCIA): Formato MM/YYYY. Faça uma BUSCA EXAUSTIVA por menções expressas da data/período de execução do serviço ou compra no corpo do texto (ex: "ref. ao mês de", "competência"). Apenas se não encontrar, use a data de emissão. E como último recurso absoluto, a data de pagamento. NUNCA DEVE FICAR NULA.
- REGRA 10 (FORNECEDOR PF/TRABALHISTA, PENSÃO ALIMENTÍCIA E CONDOMÍNIO): O fornecedor é sempre quem prestou o serviço/vendeu o produto ou gerou a obrigação trabalhista:
  (1) Em recibos de salários, férias, adiantamentos ou prestadores pessoa física, o 'nome_fornecedor' é SEMPRE o nome completo da pessoa física (funcionário/prestador) e o CPF vai em 'cnpj_cpf_fornecedor'.
  (2) REGRA MANDATÓRIA DE PENSÃO ALIMENTÍCIA: Em despesas referentes a Pensão Alimentícia descontada em folha (comprovantes de Pix, TED, recibos judiciais ou holerites), o 'nome_fornecedor' DEVE SER OBRIGATORIAMENTE O NOME DO FUNCIONÁRIO DO CONDOMÍNIO que sofreu o desconto, e NUNCA a pessoa beneficiária que recebeu o valor. O 'cnpj_cpf_fornecedor' deve ser o CPF do funcionário.
  (3) O Condomínio pagador é TERMINANTEMENTE PROIBIDO de constar como fornecedor. Se não houver número fiscal explícito, 'numero_despesa' deve ser null."""

        response_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "cnpj_cpf_fornecedor": types.Schema(type=types.Type.STRING, description="CNPJ ou CPF do fornecedor"),
                "nome_fornecedor": types.Schema(
                    type=types.Type.STRING, 
                    description="Razão Social ou Nome Fantasia completo. Se for empresa limitada, DEVE conter 'Ltda'. Title Case. NUNCA caixa alta. Acentuação pt-BR obrigatória."
                ),
                "numero_despesa": types.Schema(type=types.Type.STRING, description="Número da Nota Fiscal ou Recibo"),
                "data_emissao": types.Schema(type=types.Type.STRING, description="Data oficial de emissão do documento fiscal ou recibo. Formato YYYY-MM-DD."),
                "data_vencimento": types.Schema(type=types.Type.STRING, description="Data limite de vencimento do boleto ou fatura. Formato YYYY-MM-DD. NUNCA copiar para data_pagamento."),
                "data_pagamento": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Data do efetivo pagamento contida no comprovante bancário (Pix, TED, autenticação mecânica) em qualquer página do documento. "
                        "Se não houver nenhum comprovante, preencher OBRIGATORIAMENTE com a data de emissão fiscal. "
                        "NUNCA utilizar a data de vencimento. Formato YYYY-MM-DD."
                    )
                ),
                "valor_total_bruto": types.Schema(
                    type=types.Type.STRING,
                    description="Valor pago; em demonstrativos de pagamento de salários/adiantamento/férias, usar SEMPRE o Valor Líquido.",
                ),
                "descricao": types.Schema(
                    type=types.Type.STRING, 
                    description=(
                        "Descrição em Sentence Case com histórico contábil conciso. "
                        "Se for empresa Ltda, manter 'Ltda' antes de Danfe/NFSe (ex: 'LCM Santos Comércio Atacadista Ltda Danfe 775'). "
                        "Recibos avulsos: finalizar com 'conf. recibo' (sem ponto no final). NUNCA usar 'null'. "
                        "Nenhuma frase ou descrição termina com ponto final, salvo sufixos como 'S.A.'."
                    ),
                ),
                "contexto_sintetizado": types.Schema(
                    type=types.Type.STRING,
                    description="Definição contábil do serviço/produto, com acentuação pt-BR correta, sem caixa alta",
                ),
                "chave_acesso": types.Schema(
                    type=types.Type.STRING,
                    description="Chave de Acesso oficial da NF-e contendo exatamente 44 dígitos numéricos, sem espaços e sem pontuação. null se não existir.",
                    nullable=True,
                ),
                "competencia": types.Schema(
                    type=types.Type.STRING,
                    description="Competência contábil no formato MM/YYYY. OBRIGATÓRIO: se omisso, deduza pelo pagamento/emissão.",
                ),
            },
        )

        model_primary = os.environ.get("GEMINI_MODEL_PRIMARY", "gemini-3.5-flash-lite")
        model_fallback = os.environ.get("GEMINI_MODEL_FALLBACK", "gemini-flash-lite-latest")
        model_tertiary = "gemini-3-flash-preview"
        
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
                            delay = 10 + random.uniform(2, 8)
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
                    elif "503" in str(e) or e.code == 503:
                        if modelo_atual == model_primary:
                            novo_modelo = model_fallback
                        elif modelo_atual == model_fallback:
                            novo_modelo = model_tertiary
                        else:
                            novo_modelo = model_fallback
                        logger.warning(
                            f"Erro 503 no modelo '{modelo_atual}'. Failover para '{novo_modelo}' "
                            f"(tentativa {attempt}/{max_tentativas})."
                        )
                        modelo_atual = novo_modelo
                        delay = random.uniform(2, 4)
                        await asyncio.sleep(delay)
                    else:
                        # Para outros erros de rede (ex: SSL drop, httpx.ReadError), tenta mais uma vez
                        if attempt < max_tentativas:
                            await asyncio.sleep(2)
                        else:
                            raise e
                elif "503" in str(e):
                    if modelo_atual == model_primary:
                        novo_modelo = model_fallback
                    elif modelo_atual == model_fallback:
                        novo_modelo = model_tertiary
                    else:
                        novo_modelo = model_fallback
                    logger.warning(
                        f"Erro 503 no modelo '{modelo_atual}'. Failover para '{novo_modelo}' "
                        f"(tentativa {attempt}/{max_tentativas})."
                    )
                    modelo_atual = novo_modelo
                    delay = random.uniform(2, 4)
                    await asyncio.sleep(delay)
                else:
                    raise e

        if bruto is None:
            raise Exception("Falha na extração de dados: retorno nulo.")

        valor_processado = parse_valor_brl(bruto.valor_total_bruto) or 0.0

        # v1.57: Garantia determinística de fallback de data_pagamento
        data_pagamento_final = bruto.data_pagamento
        if not data_pagamento_final or str(data_pagamento_final).lower().strip() in ("null", "none", ""):
            data_pagamento_final = bruto.data_emissao

        comp = bruto.competencia
        if not comp or comp.strip() == "":
            fallback_date = data_pagamento_final or bruto.data_emissao or bruto.data_vencimento
            if fallback_date and len(fallback_date) >= 7:
                parts = fallback_date.split("-")
                if len(parts) >= 2:
                    comp = f"{parts[1]}/{parts[0]}"

        from src.utils.text_sanitizer import sanitize_nome_fornecedor, sanitize_descricao
        
        fornec_limpo = sanitize_nome_fornecedor(bruto.nome_fornecedor)

        dados_extraidos = DadosExtraidosDTO(
            cnpj_cpf_fornecedor=bruto.cnpj_cpf_fornecedor,
            nome_fornecedor=fornec_limpo,
            numero_despesa=bruto.numero_despesa,
            data_emissao=bruto.data_emissao,
            data_vencimento=bruto.data_vencimento,
            data_pagamento=data_pagamento_final,
            valor_total=valor_processado,
            descricao=sanitize_descricao(bruto.descricao, numero_doc=bruto.numero_despesa, nome_fornecedor=fornec_limpo),
            contexto_sintetizado=sanitize_descricao(bruto.contexto_sintetizado, numero_doc=bruto.numero_despesa, nome_fornecedor=fornec_limpo),
            chave_acesso=sanitize_chave_acesso(bruto.chave_acesso),
            competencia=comp,
        )

        return dados_extraidos, hash_arquivo
