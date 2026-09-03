import os
from dataclasses import dataclass

from google import genai
from google.genai import types


@dataclass
class ValidacaoImagem:
    aprovada: bool
    motivo: str | None = None  # preenchido apenas quando reprovada


def validar_qualidade_imagem(
    file_bytes: bytes,
    mime_type: str,
) -> ValidacaoImagem:
    """
    Usa o Gemini para avaliar se uma imagem de documento fiscal tem
    qualidade suficiente para extração de dados (OCR/IA).

    Critérios avaliados:
    - Legibilidade do texto (foco, nitidez)
    - Iluminação adequada (sem sombras graves, sem saturação)
    - Documento inteiro visível (sem cortes nas bordas)
    - Ausência de reflexos ou brilho que ocultem texto

    Retorna ValidacaoImagem com aprovada=True/False e motivo se reprovada.
    Documentos PDF são aprovados automaticamente (já são digitais).
    """

    # PDFs não precisam de validação de qualidade
    if mime_type == "application/pdf":
        return ValidacaoImagem(aprovada=True)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não encontrada nas variáveis de ambiente.")

    client = genai.Client(api_key=api_key)

    prompt = """Você é um sistema de controle de qualidade de imagens de documentos fiscais.

Avalie APENAS se esta imagem tem qualidade técnica suficiente para extração automática de dados
(OCR/IA). Não tente ler ou extrair nenhum dado — só avalie a qualidade.

Critérios de REPROVAÇÃO (basta um para reprovar):
- Texto ilegível por foco ruim, tremido ou desfocado
- Iluminação insuficiente (muito escura) ou excessiva (estourada)
- Reflexo ou brilho cobrindo partes do texto
- Documento cortado nas bordas (campos importantes fora do quadro)
- Imagem girada mais de 45 graus

Responda APENAS com JSON neste formato exato, sem nenhum texto adicional:
{"aprovada": true} 
ou
{"aprovada": false, "motivo": "<descrição curta do problema em português>"}"""

    response_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "aprovada": types.Schema(type=types.Type.BOOLEAN),
            "motivo": types.Schema(type=types.Type.STRING),
        },
        required=["aprovada"],
    )

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0,
        ),
    )

    import json
    resultado = json.loads(response.text)

    return ValidacaoImagem(
        aprovada=resultado.get("aprovada", False),
        motivo=resultado.get("motivo"),
    )
