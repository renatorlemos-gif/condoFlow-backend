"""
Testes automatizados para a US-01 (Contexto Multi-Administradora e Parser Itaú).
"""

import io
import unittest
import pandas as pd
from src.utils.itau_parser import processar_extrato_itau_bytes
from src.api.contexto_router import ADMINISTRADORAS_DEFAULT, CONDOMINIOS_DEFAULT

def test_itau_parser_sucesso():
    # Cria uma planilha Excel simulando extrato do Itaú em memória
    dados = {
        "Data": ["01/05/2026", "05/05/2026", "10/05/2026"],
        "Lançamento": ["PIX RECEBIDO CONDÔMINO 101", "TARIFA BANCARIA CESTA", "PAG BOLETO ELEVADORES OTIS"],
        "Valor": [1500.00, -85.50, -1200.00],
    }
    df_in = pd.DataFrame(dados)
    buf = io.BytesIO()
    df_in.to_excel(buf, index=False)
    buf.seek(0)

    df_out, excel_out, nome_saida = processar_extrato_itau_bytes(buf.getvalue(), "extrato_itau_teste.xlsx")

    assert not df_out.empty
    assert len(df_out) == 3
    assert "extrato_itau_processado" in nome_saida
    assert excel_out.getvalue() is not None

    # Verifica se as colunas Crédito e Débito foram geradas corretamente
    creditos = df_out["Crédito (R$)"].tolist()
    debitos = df_out["Débito (R$)"].tolist()

    assert creditos[0] == 1500.00
    assert debitos[0] == 0.0
    assert debitos[1] == 85.50
    assert debitos[2] == 1200.00

def test_contexto_defaults():
    # Valida integridade da carteira padrão das duas administradoras
    assert len(ADMINISTRADORAS_DEFAULT) == 2
    adm_ids = [a["id"] for a in ADMINISTRADORAS_DEFAULT]
    assert "adm-alpha" in adm_ids
    assert "adm-beta" in adm_ids

    # Valida condomínios vinculados
    assert len(CONDOMINIOS_DEFAULT) == 5
    condos_alpha = [c for c in CONDOMINIOS_DEFAULT if c["administradora_id"] == "adm-alpha"]
    condos_beta = [c for c in CONDOMINIOS_DEFAULT if c["administradora_id"] == "adm-beta"]

    assert len(condos_alpha) == 3
    assert len(condos_beta) == 2
