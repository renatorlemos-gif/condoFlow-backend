"""
test_v157_conciliacao_limite.py
===============================
Testes automatizados para a expansão do limite de conciliação para 500:
- listar_transacoes possui default limit de 500
- listar_transacoes respeita limit customizado quando fornecido
- despesas_disponiveis utiliza limit(500)
"""

import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.api.main import app


class TestV157ConciliacaoLimite(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

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
    def test_listar_transacoes_default_limit_500(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/conciliacao/transacoes")
        self.assertEqual(response.status_code, 200)
        mock_query.limit.assert_called_with(500)

    @patch("src.api.conciliacao_router._get_supabase")
    def test_listar_transacoes_custom_limit(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/conciliacao/transacoes?limit=250")
        self.assertEqual(response.status_code, 200)
        mock_query.limit.assert_called_with(250)

    @patch("src.api.conciliacao_router._get_supabase")
    def test_despesas_disponiveis_limit_500(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/conciliacao/despesas-disponiveis")
        self.assertEqual(response.status_code, 200)
        mock_query.limit.assert_called_with(500)

    @patch("src.api.conciliacao_router._get_supabase")
    def test_despesas_disponiveis_filtra_por_condominio_id(self, mock_get_supabase):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        condo_id = "9cc651ba-e20e-4bc1-8366-f4f0addfc28f"
        response = self.client.get(f"/api/v1/conciliacao/despesas-disponiveis?condominio_id={condo_id}")
        self.assertEqual(response.status_code, 200)
        mock_query.eq.assert_any_call("condominio_id", condo_id)
        mock_query.eq.assert_any_call("status", "validado")

    @patch("src.api.conciliacao_router._get_supabase")
    def test_despesas_disponiveis_isolamento_multi_tenant(self, mock_get_supabase):
        """Garante que despesas de outro condomínio não vazam para o condomínio atual."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        condo_corrente = "9cc651ba-e20e-4bc1-8366-f4f0addfc28f"
        doc_corrente = {
            "id": "doc-1",
            "condominio_id": condo_corrente,
            "fornecedor": "Fornecedor Local",
            "numero_doc": "123",
            "data_emissao": "2026-09-10",
            "valor_total": 150.00,
            "descricao": "Serviço Local"
        }

        def mock_table(table_name):
            if table_name == "conciliacoes":
                q = MagicMock()
                q.select.return_value = q
                q.execute.return_value = MagicMock(data=[])
                return q
            elif table_name == "despesas":
                q = MagicMock()
                q.select.return_value = q
                q.order.return_value = q
                q.limit.return_value = q
                def fake_eq(col, val):
                    if col == "condominio_id" and val == condo_corrente:
                        q.execute.return_value = MagicMock(data=[doc_corrente])
                    elif col == "condominio_id" and val != condo_corrente:
                        q.execute.return_value = MagicMock(data=[])
                    return q
                q.eq.side_effect = fake_eq
                return q
            return MagicMock()

        mock_supabase.table.side_effect = mock_table

        response = self.client.get(f"/api/v1/conciliacao/despesas-disponiveis?condominio_id={condo_corrente}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "doc-1")
        self.assertEqual(data[0]["fornecedor"], "Fornecedor Local")
