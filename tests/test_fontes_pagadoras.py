import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.api.main import app


class TestFontesPagadorasCorrente(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_cenario_03_rejeicao_requisicao_sem_condominio_id(self):
        """US-01 Cenário 03: Rejeição de requisição sem condominio_id (HTTP 422)."""
        response = self.client.get("/api/v1/fontes-pagadoras/corrente")
        self.assertEqual(response.status_code, 422)

    @patch("src.api.fontes_pagadoras_router._get_supabase")
    def test_cenario_01_identificacao_fonte_transacoes_competencia(self, mock_get_supabase):
        """US-01 Cenário 01: Identificação da fonte com base nas transações da competência."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_trans_query = MagicMock()
        mock_trans_resp = MagicMock(data=[{"fonte_pagadora_id": "8bbfa64c", "data_transacao": "2026-09-15"}])
        mock_trans_query.select.return_value.eq.return_value.gte.return_value.lte.return_value.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = mock_trans_resp

        mock_fontes_query = MagicMock()
        mock_fontes_resp = MagicMock(data=[{"id": "8bbfa64c", "nome": "Bradesco CC", "banco": "Bradesco"}])
        mock_fontes_query.select.return_value.eq.return_value.execute.return_value = mock_fontes_resp

        def table_side_effect(table_name):
            if table_name == "transacoes_extrato":
                return mock_trans_query
            elif table_name == "fontes_pagadoras":
                return mock_fontes_query
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        response = self.client.get("/api/v1/fontes-pagadoras/corrente?condominio_id=c1f1082c&mes_ano=2026-09")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["condominio_id"], "c1f1082c")
        self.assertEqual(data["mes_ano"], "2026-09")
        self.assertEqual(data["fonte_pagadora_id"], "8bbfa64c")
        self.assertEqual(data["nome"], "Bradesco CC")
        self.assertEqual(data["banco"], "Bradesco")
        self.assertEqual(data["origem"], "extrato_transacoes")

    @patch("src.api.fontes_pagadoras_router._get_supabase")
    def test_cenario_02_fallback_para_conta_padrao_quando_competencia_sem_extrato(self, mock_get_supabase):
        """US-01 Cenário 02: Fallback para conta padrão quando competência sem extrato."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_trans_query = MagicMock()
        mock_trans_empty = MagicMock(data=[])
        mock_trans_query.select.return_value.eq.return_value.gte.return_value.lte.return_value.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = mock_trans_empty
        mock_trans_query.select.return_value.eq.return_value.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = mock_trans_empty

        mock_fontes_query = MagicMock()
        mock_fontes_resp = MagicMock(data=[{"id": "itau-uuid", "nome": "Itaú CC", "banco": "Itaú"}])
        mock_fontes_query.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_fontes_resp

        def table_side_effect(table_name):
            if table_name == "transacoes_extrato":
                return mock_trans_query
            elif table_name == "fontes_pagadoras":
                return mock_fontes_query
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        response = self.client.get("/api/v1/fontes-pagadoras/corrente?condominio_id=c1f1082c&mes_ano=2026-10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["fonte_pagadora_id"], "itau-uuid")
        self.assertEqual(data["nome"], "Itaú CC")
        self.assertEqual(data["origem"], "fallback_cadastro")

    @patch("src.api.fontes_pagadoras_router._get_supabase")
    def test_fallback_para_transacao_recente_outro_mes(self, mock_get_supabase):
        """Passo 2: Fallback para transação mais recente do condomínio quando mês atual sem transações."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_trans_query = MagicMock()
        mock_trans_empty = MagicMock(data=[])
        mock_trans_query.select.return_value.eq.return_value.gte.return_value.lte.return_value.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = mock_trans_empty

        mock_trans_recent = MagicMock(data=[{"fonte_pagadora_id": "santander-uuid", "data_transacao": "2026-08-20"}])
        mock_trans_query.select.return_value.eq.return_value.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = mock_trans_recent

        mock_fontes_query = MagicMock()
        mock_fontes_resp = MagicMock(data=[{"id": "santander-uuid", "nome": "Santander CC", "banco": "Santander"}])
        mock_fontes_query.select.return_value.eq.return_value.execute.return_value = mock_fontes_resp

        def table_side_effect(table_name):
            if table_name == "transacoes_extrato":
                return mock_trans_query
            elif table_name == "fontes_pagadoras":
                return mock_fontes_query
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        response = self.client.get("/api/v1/fontes-pagadoras/corrente?condominio_id=c1f1082c&mes_ano=2026-10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["fonte_pagadora_id"], "santander-uuid")
        self.assertEqual(data["origem"], "extrato_transacoes")

    @patch("src.api.fontes_pagadoras_router._get_supabase")
    def test_cenario_04_retorno_404_quando_condominio_sem_fontes(self, mock_get_supabase):
        """US-01 Cenário 04: Retorno 404 quando Condomínio não Possui Nenhuma Fonte (RF-62)."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_trans_query = MagicMock()
        mock_trans_query.select.return_value.eq.return_value.gte.return_value.lte.return_value.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_trans_query.select.return_value.eq.return_value.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        mock_fontes_query = MagicMock()
        mock_fontes_query.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_fontes_query.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        def table_side_effect(table_name):
            if table_name == "transacoes_extrato":
                return mock_trans_query
            elif table_name == "fontes_pagadoras":
                return mock_fontes_query
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        response = self.client.get("/api/v1/fontes-pagadoras/corrente?condominio_id=condo-vazio")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Nenhuma fonte pagadora encontrada", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
