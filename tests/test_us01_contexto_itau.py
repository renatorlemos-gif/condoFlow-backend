"""
Testes automatizados para a US-01 (Contexto Multi-Administradora e Parser Itaú).
"""

import io
import unittest
import pandas as pd
from src.utils.itau_parser import processar_extrato_itau_bytes


class TestUs01ContextoItau(unittest.TestCase):
    def test_itau_parser_sucesso(self):
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

        self.assertFalse(df_out.empty)
        self.assertEqual(len(df_out), 3)
        self.assertIn("extrato_itau_processado", nome_saida)
        self.assertIsNotNone(excel_out.getvalue())

        # Verifica se as colunas Crédito e Débito foram geradas corretamente
        creditos = df_out["Crédito (R$)"].tolist()
        debitos = df_out["Débito (R$)"].tolist()

        self.assertEqual(creditos[0], 1500.00)
        self.assertEqual(debitos[0], 0.0)
        self.assertEqual(debitos[1], 85.50)
        self.assertEqual(debitos[2], 1200.00)


if __name__ == "__main__":
    unittest.main()

