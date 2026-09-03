import io
import json
import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_drive_service():
    """Cria o cliente autenticado do Google Drive via Service Account."""
    sa_json = os.environ.get("DRIVE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("DRIVE_SERVICE_ACCOUNT_JSON não encontrada nas variáveis de ambiente.")

    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, nome: str, parent_id: str) -> str:
    """Retorna o ID de uma pasta pelo nome dentro de um parent.
    Cria se não existir."""
    query = (
        f"name='{nome}' "
        f"and '{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    result = service.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])

    if files:
        return files[0]["id"]

    metadata = {
        "name": nome,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_documento(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    condo_nome: str | None = None,
) -> dict:
    """
    Faz upload de um arquivo para o Google Drive na estrutura:
    CondoFlow / <condo_nome> / <Ano-Mês> / <filename>

    Retorna dict com id e webViewLink do arquivo criado.
    """
    service = _get_drive_service()

    root_folder_id = os.environ.get("DRIVE_FOLDER_ID")
    if not root_folder_id:
        raise RuntimeError("DRIVE_FOLDER_ID não encontrada nas variáveis de ambiente.")

    condo = condo_nome or os.environ.get("CONDO_NOME", "Condominio")
    ano_mes = datetime.now().strftime("%Y-%m")  # ex: 2026-08

    # Garante a estrutura de pastas: CondoFlow / Condomínio / Ano-Mês
    condo_folder_id  = _get_or_create_folder(service, condo, root_folder_id)
    mes_folder_id    = _get_or_create_folder(service, ano_mes, condo_folder_id)

    # Upload do arquivo
    metadata = {"name": filename, "parents": [mes_folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)

    file = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    return {
        "drive_id": file.get("id"),
        "drive_url": file.get("webViewLink"),
        "pasta": f"CondoFlow / {condo} / {ano_mes}",
    }