import io
import os
import re
import uuid
from datetime import datetime

from supabase import create_client, Client


def _get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não encontradas nas variáveis de ambiente.")
    return create_client(url, key)


def _slugify(text: str) -> str:
    """Converte um nome em slug seguro para usar em nome de arquivo."""
    text = text.lower().strip()
    text = re.sub(r"[àáâãäå]", "a", text)
    text = re.sub(r"[èéêë]", "e", text)
    text = re.sub(r"[ìíîï]", "i", text)
    text = re.sub(r"[òóôõö]", "o", text)
    text = re.sub(r"[ùúûü]", "u", text)
    text = re.sub(r"[ç]", "c", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def upload_documento(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    condo_nome: str | None = None,
) -> dict:
    """
    Faz upload de um arquivo para o Supabase Storage (bucket 'documentos')
    usando um path plano com nome de arquivo contextualizado:

        {condo_slug}_{YYYY-MM-DD}_{uuid}_{filename_original}

    Não usa hierarquia de pastas — o contexto (condomínio, data) fica no
    próprio nome, facilitando a recuperação via query no banco futuramente.

    Retorna dict com path e URL assinada válida por 1 hora.
    """
    supabase = _get_supabase()

    condo = (condo_nome or os.environ.get("CONDO_NOME", "condominio")).strip()
    condo_slug = _slugify(condo)
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    uid = str(uuid.uuid4())[:8]

    # Garante que o filename original não quebre o path
    filename_safe = re.sub(r"[^\w.\-]", "_", filename)

    path = f"{condo_slug}_{data_hoje}_{uid}_{filename_safe}"

    supabase.storage.from_("documentos").upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": mime_type, "upsert": "true"},
    )

    signed = supabase.storage.from_("documentos").create_signed_url(path, expires_in=3600)
    signed_url = signed.get("signedURL") or signed.get("signedUrl") or ""

    return {
        "path": path,
        "signed_url": signed_url,
        "pasta": "documentos",
    }