import os
import re
import uuid
from datetime import datetime

from supabase import create_client, Client


def _get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL ou SUPABASE_SERVICE_KEY não encontradas nas variáveis de ambiente."
        )
    return create_client(url, key)


def _slugify(text: str) -> str:
    """Converte nome em slug seguro para usar em nome de arquivo."""
    text = text.lower().strip()
    for src, dst in [
        ("àáâãäå", "a"), ("èéêë", "e"), ("ìíîï", "i"),
        ("òóôõö", "o"), ("ùúûü", "u"), ("ç", "c"),
    ]:
        for ch in src:
            text = text.replace(ch, dst)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _build_filename(prefix: str, original_filename: str) -> str:
    """
    Monta nome de arquivo contextualizado:
        {prefix}_{YYYY-MM-DD}_{uuid8}_{filename_safe}
    """
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    uid = str(uuid.uuid4())[:8]
    filename_safe = re.sub(r"[^\w.\-]", "_", original_filename)
    return f"{prefix}_{data_hoje}_{uid}_{filename_safe}"


# ------------------------------------------------------------------ #
#  Upload de documento fiscal (foto/PDF de NF ou recibo)             #
#  Bucket: condominios  |  Pasta: documentos/                        #
# ------------------------------------------------------------------ #

def upload_documento(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    condo_nome: str | None = None,
) -> dict:
    """
    Salva foto ou PDF de documento fiscal no Supabase Storage.

    Estrutura:
        bucket: condominios
        path:   documentos/{condo-slug}_{YYYY-MM-DD}_{uuid}_{filename}

    Retorna dict com path e URL assinada (válida 1h).
    """
    supabase = _get_supabase()
    bucket   = os.environ.get("SUPABASE_BUCKET_CONDOMINIOS", "condominios")
    condo    = (condo_nome or os.environ.get("CONDO_NOME", "condominio")).strip()
    prefix   = _slugify(condo)
    path     = f"documentos/{_build_filename(prefix, filename)}"

    supabase.storage.from_(bucket).upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": mime_type, "upsert": "true"},
    )

    signed     = supabase.storage.from_(bucket).create_signed_url(path, expires_in=3600)
    signed_url = signed.get("signedURL") or signed.get("signedUrl") or ""

    return {"path": path, "signed_url": signed_url, "bucket": bucket}


# ------------------------------------------------------------------ #
#  Upload de extrato bancário original (OFX/CSV/XLS)                 #
#  Bucket: condominios  |  Pasta: extratos/                          #
# ------------------------------------------------------------------ #

def upload_extrato(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    condo_nome: str | None = None,
) -> dict:
    """
    Salva o arquivo original de extrato bancário enviado pelo usuário.

    Estrutura:
        bucket: condominios
        path:   extratos/{condo-slug}_{YYYY-MM-DD}_{uuid}_{filename}
    """
    supabase = _get_supabase()
    bucket   = os.environ.get("SUPABASE_BUCKET_CONDOMINIOS", "condominios")
    condo    = (condo_nome or os.environ.get("CONDO_NOME", "condominio")).strip()
    prefix   = _slugify(condo)
    path     = f"extratos/{_build_filename(prefix, filename)}"

    supabase.storage.from_(bucket).upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": mime_type, "upsert": "true"},
    )

    signed     = supabase.storage.from_(bucket).create_signed_url(path, expires_in=3600)
    signed_url = signed.get("signedURL") or signed.get("signedUrl") or ""

    return {"path": path, "signed_url": signed_url, "bucket": bucket}


# ------------------------------------------------------------------ #
#  Upload de extrato processado (XLSX gerado pelo backend)           #
#  Bucket: condominios  |  Pasta: extratos-processados/              #
# ------------------------------------------------------------------ #

def upload_extrato_processado(
    file_bytes: bytes,
    filename: str,
    condo_nome: str | None = None,
) -> dict:
    """
    Salva o XLSX consolidado gerado pelo processamento do extrato.

    Estrutura:
        bucket: condominios
        path:   extratos-processados/{condo-slug}_{YYYY-MM-DD}_{uuid}_{filename}
    """
    supabase  = _get_supabase()
    bucket    = os.environ.get("SUPABASE_BUCKET_CONDOMINIOS", "condominios")
    condo     = (condo_nome or os.environ.get("CONDO_NOME", "condominio")).strip()
    prefix    = _slugify(condo)
    path      = f"extratos-processados/{_build_filename(prefix, filename)}"
    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    supabase.storage.from_(bucket).upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": mime_type, "upsert": "true"},
    )

    signed     = supabase.storage.from_(bucket).create_signed_url(path, expires_in=3600)
    signed_url = signed.get("signedURL") or signed.get("signedUrl") or ""

    return {"path": path, "signed_url": signed_url, "bucket": bucket}