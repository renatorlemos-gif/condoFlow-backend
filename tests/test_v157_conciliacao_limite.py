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
