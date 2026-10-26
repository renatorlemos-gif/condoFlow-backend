"""
test_v154_filtro_competencia_limite.py
======================================
Testes automatizados BDD para o épico delta v1.54:
Filtro de Competência e Expansão de Limite na Validação de Despesas.

Cenários cobertos:
- Cenário 01: Filtragem por competência temporal (mes_ano) no backend com .or_()
- Cenário 02: Elevação do limite padrão para 500 despesas
- Cenário 03: Exibição fidedigna de contadores e despesas "Aguardando" (ex: 5 faturas Ampla Energia)
- Cenário 04: Ordenação e estabilidade temporal (data_pagamento DESC, criado_em DESC)
- Cenário 05: Fallback temporal para data_emissao quando data_pagamento for nula
- Cenário 06: Retrocompatibilidade e resiliência quando mes_ano não for informado
- Suporte a variações de formato: 'YYYY-MM' e 'MM/YYYY'
"""

import unittest
from unittest.mock import MagicMock, patch, call
from fastapi.testclient import TestClient
from src.api.main import app


class TestV154FiltroCompetenciaLimite(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _build_mock_query(self, return_data=None):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.or_.return_value = query
        query.in_.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value = MagicMock(data=return_data if return_data is not None else [])
        return query

    @patch("src.api.validacao_router._get_supabase")
    def test_cenario_01_filtragem_por_competencia_temporal_mes_ano(self, mock_get_supabase):
        """Cenário 01: Filtragem por competência temporal (mes_ano=2026-09) com cláusula PostgREST .or_()."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[
            {
                "id": "doc-1",
                "filename": "fatura_energia.pdf",
                "status": "extraido",
                "fornecedor": "Ampla Energia e Serviços S.A.",
                "data_pagamento": "2026-09-14",
                "data_emissao": "2026-09-02",
                "administradora_id": None,
                "condominio_id": "c1f1082c",
                "fonte_pagadora_id": None
            }
        ])
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/validacao/despesas?status=todos&condominio_id=c1f1082c&mes_ano=2026-09")
        self.assertEqual(response.status_code, 200)

        # Verifica que o filtro .or_ foi chamado com o intervalo do mês e fallback data_emissao
        mock_query.or_.assert_called_once()
        filtro_or = mock_query.or_.call_args[0][0]
        expected_inicio = "2026-09-01"
        expected_fim = "2026-09-30"
        self.assertIn(f"data_pagamento.gte.{expected_inicio}", filtro_or)
        self.assertIn(f"data_pagamento.lte.{expected_fim}", filtro_or)
        self.assertIn("data_pagamento.is.null", filtro_or)
        self.assertIn(f"data_emissao.gte.{expected_inicio}", filtro_or)
        self.assertIn(f"data_emissao.lte.{expected_fim}", filtro_or)

    @patch("src.api.validacao_router._get_supabase")
    def test_cenario_01_variacao_formato_mes_ano_barra(self, mock_get_supabase):
        """Cenário 01 (Variação): Formato '09/2026' deve ser normalizado para 2026-09."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/validacao/despesas?status=todos&condominio_id=c1f1082c&mes_ano=09/2026")
        self.assertEqual(response.status_code, 200)

        mock_query.or_.assert_called_once()
        filtro_or = mock_query.or_.call_args[0][0]
        self.assertIn("data_pagamento.gte.2026-09-01", filtro_or)
        self.assertIn("data_pagamento.lte.2026-09-30", filtro_or)

    @patch("src.api.validacao_router._get_supabase")
    def test_cenario_02_elevacao_limite_padrao_500(self, mock_get_supabase):
        """Cenário 02: Limite padrão deve ser 500 e respeitar valor passado pela requisição."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        # Chamada sem especificar limit -> padrão 500
        response = self.client.get("/api/v1/validacao/despesas?status=todos&condominio_id=c1f1082c&mes_ano=2026-09")
        self.assertEqual(response.status_code, 200)
        mock_query.limit.assert_called_with(500)

        # Chamada explicitando limit=500
        mock_query.reset_mock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.or_.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        response2 = self.client.get("/api/v1/validacao/despesas?status=todos&limit=500&condominio_id=c1f1082c&mes_ano=2026-09")
        self.assertEqual(response2.status_code, 200)
        mock_query.limit.assert_called_with(500)

    @patch("src.api.validacao_router._get_supabase")
    def test_cenario_03_contadores_e_despesas_aguardando_ampla(self, mock_get_supabase):
        """Cenário 03: Despesas com status 'extraido' são retornadas sem truncamento."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        # Simula 111 despesas: 106 conciliados e 5 extraidos da Ampla Energia
        docs_mock = [
            {
                "id": f"conciliado-{i}",
                "filename": f"despesa_{i}.pdf",
                "status": "conciliado",
                "fornecedor": f"Fornecedor {i}",
                "data_pagamento": "2026-09-10",
                "data_emissao": "2026-09-01",
                "administradora_id": None,
                "condominio_id": "83262090-73af-41ef-8fb5-83dfb67ecb14",
                "fonte_pagadora_id": None
            } for i in range(106)
        ] + [
            {
                "id": f"extraido-ampla-{i}",
                "filename": f"fatura_ampla_{i}.pdf",
                "status": "extraido",
                "fornecedor": "Ampla Energia e Serviços S.A.",
                "data_pagamento": "2026-09-14",
                "data_emissao": "2026-09-02",
                "administradora_id": None,
                "condominio_id": "83262090-73af-41ef-8fb5-83dfb67ecb14",
                "fonte_pagadora_id": None
            } for i in range(5)
        ]

        mock_query = self._build_mock_query(return_data=docs_mock)
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/validacao/despesas?status=todos&limit=500&condominio_id=83262090-73af-41ef-8fb5-83dfb67ecb14&mes_ano=2026-09")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 111)

        aguardando = [d for d in data if d["status"] == "extraido"]
        conciliados = [d for d in data if d["status"] == "conciliado"]
        self.assertEqual(len(aguardando), 5)
        self.assertEqual(len(conciliados), 106)
        for a in aguardando:
            self.assertEqual(a["fornecedor"], "Ampla Energia e Serviços S.A.")

    @patch("src.api.validacao_router._get_supabase")
    def test_cenario_04_ordenacao_composta(self, mock_get_supabase):
        """Cenário 04: Ordenação primária por data_pagamento DESC e secundária por criado_em DESC."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/validacao/despesas?status=todos&condominio_id=c1f1082c&mes_ano=2026-09")
        self.assertEqual(response.status_code, 200)

        # Verifica chamadas de order
        mock_query.order.assert_has_calls([
            call("data_pagamento", desc=True),
            call("criado_em", desc=True)
        ], any_order=False)

    @patch("src.api.validacao_router._get_supabase")
    def test_cenario_05_fallback_data_emissao_quando_data_pagamento_nula(self, mock_get_supabase):
        """Cenário 05: Fallback temporal para data_emissao quando data_pagamento for nula."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        # Despesa recém-extraída com data_pagamento None e data_emissao no mês
        doc_recem_extraido = {
            "id": "doc-pendente-1",
            "filename": "fatura_recente.pdf",
            "status": "extraido",
            "fornecedor": "Fornecedor Sem Pgto",
            "data_pagamento": None,
            "data_emissao": "2026-09-15",
            "administradora_id": None,
            "condominio_id": "c1f1082c",
            "fonte_pagadora_id": None
        }

        mock_query = self._build_mock_query(return_data=[doc_recem_extraido])
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/validacao/despesas?status=todos&condominio_id=c1f1082c&mes_ano=2026-09")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertIsNone(data[0]["data_pagamento"])
        self.assertEqual(data[0]["data_emissao"], "2026-09-15")

    @patch("src.api.validacao_router._get_supabase")
    def test_cenario_06_retrocompatibilidade_sem_mes_ano(self, mock_get_supabase):
        """Cenário 06: Requisição sem mes_ano não aplica cláusula .or_() temporal e responde 200 OK."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        response = self.client.get("/api/v1/validacao/despesas?status=todos&condominio_id=c1f1082c")
        self.assertEqual(response.status_code, 200)

        # Não deve chamar or_ quando mes_ano não é informado
        mock_query.or_.assert_not_called()
        # Deve respeitar limit padrão de 500
        mock_query.limit.assert_called_with(500)
        # Deve manter ordenação
        mock_query.order.assert_called()


if __name__ == "__main__":
    unittest.main()
