"""
test_v158_restauracao_agrupamentos.py
=====================================
Testes automatizados para a versão v1.58:
- US-01: Ingestão integral de todas as movimentações no banco (extrato_service.py)
  * Todas as categorias são persistidas (sem descarte)
  * Metadados {"categoria": categoria} preenchidos fielmente
  * Fallback seguro para "Sem Categoria" quando nula ou em branco
  * Normalização via strip()
- US-02: Consulta irrestrita no endpoint de conciliação (conciliacao_router.py)
  * Remoção do filtro compulsório .eq("metadados->>categoria", "Outros Gastos")
  * Entrega de todas as categorias na resposta da API
  * Mapeamento do atributo categoria com fallback para "Sem Categoria"
"""

import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from fastapi.testclient import TestClient

from src.services.extrato_service import _salvar_transacoes
from src.api.main import app


class TestV158RestauracaoAgrupamentos(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    # -------------------------------------------------------------
    # US-01: Ingestão Integral em extrato_service._salvar_transacoes
    # -------------------------------------------------------------
    @patch("src.services.extrato_service._get_supabase")
    def test_salvar_transacoes_persiste_todas_as_categorias(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table

        df = pd.DataFrame([
            {
                "Data_Valida": "2026-10-01",
                "Lançamento": "PGTO ELEVADORES",
                "Categoria": "Outros Gastos",
                "Débito (R$)": 1250.00,
                "Crédito (R$)": 0.0,
            },
            {
                "Data_Valida": "2026-10-02",
                "Lançamento": "TAR MANUT CONTA",
                "Categoria": "Tarifas",
                "Débito (R$)": 45.90,
                "Crédito (R$)": 0.0,
            },
            {
                "Data_Valida": "2026-10-03",
                "Lançamento": "CREDITO TAXA CONDOMINIAL",
                "Categoria": "Receitas",
                "Débito (R$)": 0.0,
                "Crédito (R$)": 35000.00,
            },
            {
                "Data_Valida": "2026-10-04",
                "Lançamento": "APLICACAO CONTAMAX",
                "Categoria": "Aplicações",
                "Débito (R$)": 5000.00,
                "Crédito (R$)": 0.0,
            },
        ])

        qtd = _salvar_transacoes(
            df=df,
            banco="bradesco",
            storage_path="extratos-processados/condo1/extrato.xlsx",
            administradora_id="adm-alpha",
            condominio_id="condo-alpha-01",
        )

        self.assertEqual(qtd, 4, "Todas as 4 transações de diferentes categorias devem ser salvas")
        mock_table.insert.assert_called_once()
        registros_inseridos = mock_table.insert.call_args[0][0]
        self.assertEqual(len(registros_inseridos), 4)

        categorias_salvas = [r["metadados"]["categoria"] for r in registros_inseridos]
        self.assertEqual(categorias_salvas, ["Outros Gastos", "Tarifas", "Receitas", "Aplicações"])

    @patch("src.services.extrato_service._get_supabase")
    def test_salvar_transacoes_fallback_sem_categoria(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table

        df = pd.DataFrame([
            {
                "Data_Valida": "2026-10-05",
                "Lançamento": "LANCAMENTO SEM CATEGORIA DEFINIDA",
                "Categoria": None,
                "Débito (R$)": 100.00,
                "Crédito (R$)": 0.0,
            },
            {
                "Data_Valida": "2026-10-06",
                "Lançamento": "LANCAMENTO ESPACOS EM BRANCO",
                "Categoria": "   ",
                "Débito (R$)": 50.00,
                "Crédito (R$)": 0.0,
            },
        ])

        qtd = _salvar_transacoes(
            df=df,
            banco="santander",
            storage_path="extratos-processados/condo1/extrato.xlsx",
        )

        self.assertEqual(qtd, 2)
        registros_inseridos = mock_table.insert.call_args[0][0]
        for r in registros_inseridos:
            self.assertEqual(r["metadados"]["categoria"], "Sem Categoria")

    @patch("src.services.extrato_service._get_supabase")
    def test_salvar_transacoes_normalizacao_categoria_strip(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table

        df = pd.DataFrame([
            {
                "Data_Valida": "2026-10-07",
                "Lançamento": "TARIFA COM ESPACOS",
                "Categoria": "  Tarifas  ",
                "Débito (R$)": 25.00,
                "Crédito (R$)": 0.0,
            }
        ])

        qtd = _salvar_transacoes(
            df=df,
            banco="itau",
            storage_path="extratos-processados/condo1/extrato.xlsx",
        )

        self.assertEqual(qtd, 1)
        registros_inseridos = mock_table.insert.call_args[0][0]
        self.assertEqual(registros_inseridos[0]["metadados"]["categoria"], "Tarifas")

    # -------------------------------------------------------------
    # US-02: Rota GET /api/v1/conciliacao/transacoes sem filtro fixo
    # -------------------------------------------------------------
    def _build_mock_query(self, return_data=None):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.gte.return_value = query
        query.lte.return_value = query
        query.in_.return_value = query
        query.execute.return_value = MagicMock(data=return_data if return_data is not None else [])
        return query

    @patch("src.api.conciliacao_router._get_supabase")
    def test_endpoint_transacoes_sem_filtro_compulsorio_e_retorna_todas_categorias(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        transacoes_mock = [
            {
                "id": "t1",
                "data_transacao": "2026-10-01",
                "descricao": "TARIFA DE COBRANCA",
                "valor": 12.50,
                "tipo": "debito",
                "banco": "bradesco",
                "metadados": {"categoria": "Tarifas"},
            },
            {
                "id": "t2",
                "data_transacao": "2026-10-02",
                "descricao": "MANUTENCAO ELEVADOR",
                "valor": 950.00,
                "tipo": "debito",
                "banco": "bradesco",
                "metadados": {"categoria": "Outros Gastos"},
            },
            {
                "id": "t3",
                "data_transacao": "2026-10-03",
                "descricao": "CONDOMINIO RECEBIDO",
                "valor": 45000.00,
                "tipo": "credito",
                "banco": "bradesco",
                "metadados": {"categoria": "Receitas"},
            },
        ]

        # Table query mocks
        query_trans = self._build_mock_query(return_data=transacoes_mock)
        query_conc = self._build_mock_query(return_data=[])
        query_despesas = self._build_mock_query(return_data=[])

        def table_side_effect(table_name):
            if table_name == "transacoes_extrato":
                return query_trans
            elif table_name == "conciliacoes":
                return query_conc
            elif table_name == "despesas":
                return query_despesas
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        response = self.client.get("/api/v1/conciliacao/transacoes?mes_ano=2026-10&condominio_id=condo-1")
        self.assertEqual(response.status_code, 200)

        # Assere que eq("metadados->>categoria", "Outros Gastos") NUNCA foi chamado
        for call_item in query_trans.eq.call_args_list:
            campo, valor = call_item[0]
            self.assertNotEqual(campo, "metadados->>categoria", "Não deve filtrar compulsoriamente por metadados->>categoria")

        data = response.json()
        self.assertEqual(len(data), 3, "Deve retornar as 3 transações de todas as categorias")
        categorias = [item["categoria"] for item in data]
        self.assertEqual(categorias, ["Tarifas", "Outros Gastos", "Receitas"])

    @patch("src.api.conciliacao_router._get_supabase")
    def test_endpoint_transacoes_fallback_sem_categoria(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        transacoes_mock = [
            {
                "id": "t1",
                "data_transacao": "2026-10-05",
                "descricao": "LANCAMENTO ANTIGO SEM METADADOS",
                "valor": 100.00,
                "tipo": "debito",
                "banco": "bradesco",
                "metadados": None,
            },
            {
                "id": "t2",
                "data_transacao": "2026-10-06",
                "descricao": "LANCAMENTO COM METADADOS VAZIOS",
                "valor": 200.00,
                "tipo": "debito",
                "banco": "bradesco",
                "metadados": {"categoria": ""},
            },
        ]

        query_trans = self._build_mock_query(return_data=transacoes_mock)
        query_conc = self._build_mock_query(return_data=[])
        query_despesas = self._build_mock_query(return_data=[])

        def table_side_effect(table_name):
            if table_name == "transacoes_extrato":
                return query_trans
            elif table_name == "conciliacoes":
                return query_conc
            elif table_name == "despesas":
                return query_despesas
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        response = self.client.get("/api/v1/conciliacao/transacoes?mes_ano=2026-10")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["categoria"], "Sem Categoria")
        self.assertEqual(data[1]["categoria"], "Sem Categoria")


if __name__ == "__main__":
    unittest.main()
