"""
test_bradesco_parser.py
=======================
Testes automatizados para o parser de extratos do Bradesco:
- Classificação correta de tarifas bancárias (DOC/TED, TARIFA, TAR, IOF)
- Preservação de transferências reais como Outros Gastos (TED DIF.TITUL.CC...)
"""

import io
import unittest
import pandas as pd
from src.utils.bradesco_parser import processar_extrato_bradesco_bytes


class TestBradescoParser(unittest.TestCase):
    def _criar_extrato_bradesco_mock(self, lancamentos: list[tuple[str, str, float, float]]) -> bytes:
        """
        Cria um arquivo Excel nos moldes do extrato Bradesco:
        - 7 linhas de metadados / cabeçalho
        - Linha 7: Data | Lançamento | Docto | Crédito (R$) | Débito (R$) | Saldo (R$)
        - Linha 8+: Transações
        """
        rows = [
            ["Banco Bradesco S.A."],
            ["Agência: 1234", "Conta: 56789-0"],
            ["Extrato de: 01/09/2026 até 30/09/2026"],
            [],
            [],
            [],
            [],
            ["Data", "Lançamento", "Docto.", "Crédito (R$)", "Débito (R$)", "Saldo (R$)"],
            ["01/09/2026", "SALDO ANTERIOR", "", "", "", "10.000,00"],
        ]

        for dt, desc, cred, deb in lancamentos:
            cred_str = f"{cred:.2f}".replace(".", ",") if cred > 0 else ""
            deb_str = f"{deb:.2f}".replace(".", ",") if deb > 0 else ""
            rows.append([dt, desc, "12345", cred_str, deb_str, "9.000,00"])

        output = io.BytesIO()
        df_mock = pd.DataFrame(rows)
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df_mock.to_excel(writer, index=False, header=False)
        return output.getvalue()

    def test_doc_ted_internet_classificado_como_tarifas(self):
        """Movimentos DOC/TED INTERNET TED INTERNET devem ser categorizados como Tarifas."""
        lancamentos = [
            ("17/09/2026", "DOC/TED INTERNET TED INTERNET", 0.0, 13.85),
            ("17/09/2026", "TED DIF.TITUL.CC H.BANK DEST. francione fernandes", 0.0, 1621.00),
            ("17/09/2026", "PAGTO ELETRONICO TRIBUTO INTERNET --RECEITA FEDERA", 0.0, 6186.30),
            ("15/09/2026", "TARIFA BANCARIA CESTA", 0.0, 45.00),
            ("15/09/2026", "TAR COBRANCA", 0.0, 10.50),
            ("15/09/2026", "IOF OPERACOES", 0.0, 3.20),
        ]
        conteudo = self._criar_extrato_bradesco_mock(lancamentos)
        df, excel_io, nome_saida = processar_extrato_bradesco_bytes(conteudo, "extrato_bradesco.xlsx")

        self.assertIsNotNone(df)
        self.assertFalse(df.empty)

        # Verifica DOC/TED INTERNET
        row_doc_ted = df[df["Lançamento"].str.contains("DOC/TED INTERNET", na=False)]
        self.assertEqual(len(row_doc_ted), 1)
        self.assertEqual(row_doc_ted.iloc[0]["Categoria"], "Tarifas")

        # Verifica outras tarifas
        row_tarifa = df[df["Lançamento"].str.contains("TARIFA BANCARIA", na=False)]
        self.assertEqual(row_tarifa.iloc[0]["Categoria"], "Tarifas")

        row_tar = df[df["Lançamento"].str.contains("TAR COBRANCA", na=False)]
        self.assertEqual(row_tar.iloc[0]["Categoria"], "Tarifas")

        row_iof = df[df["Lançamento"].str.contains("IOF OPERACOES", na=False)]
        self.assertEqual(row_iof.iloc[0]["Categoria"], "Tarifas")

        # Verifica que TED de transferência legítima continua como Outros Gastos
        row_ted_transf = df[df["Lançamento"].str.contains("TED DIF.TITUL", na=False)]
        self.assertEqual(len(row_ted_transf), 1)
        self.assertEqual(row_ted_transf.iloc[0]["Categoria"], "Outros Gastos")
