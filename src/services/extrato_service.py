"""
extrato_service.py
==================
Orquestra o processamento de extratos bancários:

1. Salva o arquivo original no Supabase Storage (extratos/)
2. Processa via parser (Bradesco ou Santander) gerando o DataFrame + XLSX
3. Salva o XLSX gerado no Supabase Storage (extratos-processados/)
4. Persiste cada transação em transacoes_extrato no banco
5. Retorna o XLSX em memória para download imediato (comportamento atual mantido)
"""

import io
import os
from datetime import datetime, timezone

from supabase import create_client

from src.utils.supabase_storage import upload_extrato, upload_extrato_processado


def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configuradas.")
    return create_client(url, key)


def _salvar_transacoes(
    df,
    banco: str,
    condo_nome: str,
    storage_path: str,
    administradora_id: str = "adm-alpha",
    condominio_id: str = "condo-alpha-01",
) -> int:
    """
    Persiste as transações do DataFrame em transacoes_extrato com contexto de administradora e condomínio.
    Retorna o número de linhas inseridas.
    """
    supabase = _get_supabase()
    registros = []

    for _, row in df.iterrows():
        credito = float(row.get("Crédito (R$)", 0.0) or 0.0)
        debito  = float(row.get("Débito (R$)",  0.0) or 0.0)

        # Cada linha vira uma transação — crédito e débito numa mesma linha
        # são raros mas possíveis (ex: estorno parcial). Tratamos separado.
        if credito > 0:
            registros.append({
                "administradora_id": administradora_id,
                "condominio_id":     condominio_id,
                "condo_nome":        condo_nome,
                "banco":             banco,
                "data_transacao":    _parse_date(row.get("Data_Valida")),
                "descricao":         str(row.get("Lançamento", "") or ""),
                "valor":             credito,
                "tipo":              "credito",
                "storage_path":      storage_path,
                "metadados":         {"categoria": row.get("Categoria", "")},
                "criado_em":         datetime.now(timezone.utc).isoformat(),
            })

        if debito > 0:
            registros.append({
                "administradora_id": administradora_id,
                "condominio_id":     condominio_id,
                "condo_nome":        condo_nome,
                "banco":             banco,
                "data_transacao":    _parse_date(row.get("Data_Valida")),
                "descricao":         str(row.get("Lançamento", "") or ""),
                "valor":             debito,
                "tipo":              "debito",
                "storage_path":      storage_path,
                "metadados":         {"categoria": row.get("Categoria", "")},
                "criado_em":         datetime.now(timezone.utc).isoformat(),
            })

    if registros:
        supabase.table("transacoes_extrato").insert(registros).execute()

    return len(registros)


def _parse_date(val) -> str | None:
    """Converte DD/MM/YYYY para YYYY-MM-DD (formato ISO aceito pelo Postgres)."""
    if not val:
        return None
    s = str(val).strip()
    if len(s) == 10 and s[2] == "/" and s[5] == "/":
        d, m, y = s.split("/")
        return f"{y}-{m}-{d}"
    return s  # já em outro formato, passa direto


async def processar_e_persistir(
    conteudo_bytes: bytes,
    nome_arquivo: str,
    banco: str,
    condo_nome: str,
    administradora_id: str = "adm-alpha",
    condominio_id: str = "condo-alpha-01",
) -> tuple[io.BytesIO, str, int]:
    """
    Ponto de entrada principal. Retorna (excel_io, nome_saida, qtd_transacoes).

    O XLSX é retornado para download imediato — mesmo comportamento atual.
    A persistência no banco é feita em paralelo, com isolamento multi-condomínio.
    """

    # 1. Salva o arquivo original no Supabase Storage
    mime_original = _mime_from_nome(nome_arquivo)
    storage_result = upload_extrato(
        file_bytes=conteudo_bytes,
        filename=nome_arquivo,
        mime_type=mime_original,
        condo_nome=condo_nome,
    )
    storage_path = storage_result["path"]

    # 2. Processa via parser e obtém DataFrame + XLSX
    df, excel_io, nome_saida = _chamar_parser(conteudo_bytes, nome_arquivo, banco)

    # 3. Salva o XLSX processado no Supabase Storage
    excel_io.seek(0)
    xlsx_bytes = excel_io.read()
    upload_extrato_processado(
        file_bytes=xlsx_bytes,
        filename=nome_saida,
        condo_nome=condo_nome,
    )
    excel_io.seek(0)  # rebobina para o download

    # 4. Persiste as transações no banco com administradora_id e condominio_id
    qtd = 0
    if df is not None and not df.empty:
        qtd = _salvar_transacoes(
            df=df,
            banco=banco,
            condo_nome=condo_nome,
            storage_path=storage_path,
            administradora_id=administradora_id,
            condominio_id=condominio_id,
        )

    return excel_io, nome_saida, qtd


def _chamar_parser(conteudo_bytes, nome_arquivo, banco):
    """
    Chama o parser correto e retorna (df, excel_io, nome_saida).
    Suporte a Bradesco, Santander e Itaú.
    """
    banco = banco.strip().lower()
    if banco == "bradesco":
        from src.utils.bradesco_parser import processar_extrato_bradesco_bytes
        return processar_extrato_bradesco_bytes(conteudo_bytes, nome_arquivo)
    elif banco == "santander":
        from src.utils.santander_parser import processar_extrato_santander_bytes
        return processar_extrato_santander_bytes(conteudo_bytes, nome_arquivo)
    elif banco == "itau":
        from src.utils.itau_parser import processar_extrato_itau_bytes
        return processar_extrato_itau_bytes(conteudo_bytes, nome_arquivo)
    else:
        raise ValueError(f"Banco não suportado: '{banco}'")


def _mime_from_nome(nome: str) -> str:
    ext = nome.rsplit(".", 1)[-1].lower()
    return {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls":  "application/vnd.ms-excel",
        "csv":  "text/csv",
        "ofx":  "application/ofx",
    }.get(ext, "application/octet-stream")
