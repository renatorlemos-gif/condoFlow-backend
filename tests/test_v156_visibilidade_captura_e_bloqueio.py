"""
test_v156_visibilidade_captura_e_bloqueio.py
============================================
Suite de Testes Automatizados TDD / BDD para o Release v1.56:
Visibilidade de Capturas e Bloqueio Orientado de Despesas Fora do Período.

Cenários cobertos (BDD 01 a 09):
- Cenário 01: Inclusão incondicional de despesas pendentes/não validadas no GET /despesas mesmo fora do mês
- Cenário 02: Preservação da filtragem estrita temporal para despesas já finalizadas (validado, conciliado)
- Cenário 03: Identificação de data de pagamento fora da competência
- Cenário 04: Bloqueio impeditivo com mensagem orientadora no PATCH
- Cenário 05: Desbloqueio e validação com sucesso após ajuste da data para o mês ativo
- Cenário 06: Ação direta de exclusão de despesa (DELETE /despesas/{id})
- Cenário 07: Validação defensiva no backend retornando HTTP 422 com formato DD/MM/YYYY
- Cenário 08: Isolamento estrito por condomínio com cláusula OR combinada ao eq(condominio_id)
- Cenário 09: Despesa com data de pagamento nula e status pendente/extraído
"""

import unittest
from unittest.mock import MagicMock, patch
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.validacao_router import _validar_despesa_impl, deletar_despesa, ValidacaoPayload


class TestV156VisibilidadeCapturaEBloqueio(unittest.IsolatedAsyncioTestCase):
    """Testes dos cenários BDD 01 a 09 para o épico v1.56."""

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

    def _setup_mock_despesa(self, status="extraido"):
        supabase_mock = MagicMock()
        supabase_mock.table("despesas").select().eq().single().execute.return_value.data = {
            "id": "desp-v156-01",
            "status": status,
            "condominio_id": "cond-lirios-01",
            "administradora_id": "adm-01",
            "sugestao_contabil": {"conta_debito_codigo": "1.1.01"}
        }
        supabase_mock.table("plano_contas").select().eq().eq().execute.return_value.data = [
            {"id": "conta-uuid-01", "codigo_contabil": "1.1.01"}
        ]
        supabase_mock.table("despesas").update().eq().execute.return_value = MagicMock()
        return supabase_mock

    # ------------------------------------------------------------------ #
    # Cenário 01: Inclusão incondicional de despesas pendentes na lista  #
    # ------------------------------------------------------------------ #
    @patch("src.api.validacao_router._get_supabase")
    def test_cenario01_despesa_extraida_fora_do_mes_retornada_na_listagem(self, mock_get_supabase):
        """Cenário 01: Cláusula OR inclui status.in.(extraido,pendente,extraindo,erro) e retorna doc fora do mês."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        despesa_fora_mes = {
            "id": "desp-002-outubro",
            "filename": "comprovante_gas_outubro.pdf",
            "fornecedor": "Naturgy Gás",
            "valor_total": 312.80,
            "data_emissao": "2026-09-28",
            "data_pagamento": "2026-10-01",
            "status": "extraido",
            "administradora_id": None,
            "condominio_id": "cond-lirios-01",
            "fonte_pagadora_id": None
        }

        mock_query = self._build_mock_query(return_data=[despesa_fora_mes])
        mock_supabase.table.return_value = mock_query

        response = self.client.get(
            "/api/v1/validacao/despesas?status=todos&condominio_id=cond-lirios-01&mes_ano=2026-09"
        )
        self.assertEqual(response.status_code, 200)
        dados = response.json()
        self.assertEqual(len(dados), 1)
        self.assertEqual(dados[0]["id"], "desp-002-outubro")
        self.assertEqual(dados[0]["data_pagamento"], "2026-10-01")
        self.assertEqual(dados[0]["status"], "extraido")

        # Verifica construção da cláusula OR PostgREST com inclusão incondicional de status pendentes
        mock_query.or_.assert_called_once()
        filtro_or = mock_query.or_.call_args[0][0]
        self.assertIn("data_pagamento.gte.2026-09-01", filtro_or)
        self.assertIn("data_pagamento.lte.2026-09-30", filtro_or)
        self.assertIn("data_pagamento.is.null", filtro_or)
        self.assertIn("status.in.(extraido,pendente,extraindo,erro)", filtro_or)

    # ------------------------------------------------------------------ #
    # Cenário 02: Preservação da filtragem para despesas finalizadas     #
    # ------------------------------------------------------------------ #
    @patch("src.api.validacao_router._get_supabase")
    def test_cenario02_despesas_finalizadas_fora_do_mes_nao_sao_incluidas_no_status_or(self, mock_get_supabase):
        """Cenário 02: Despesas com status 'validado' ou 'conciliado' só entram se data_pagamento estiver no mês."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        response = self.client.get(
            "/api/v1/validacao/despesas?status=todos&condominio_id=cond-lirios-01&mes_ano=2026-09"
        )
        self.assertEqual(response.status_code, 200)

        filtro_or = mock_query.or_.call_args[0][0]
        # O predicado de status só atinge extraido, pendente, extraindo, erro
        self.assertIn("status.in.(extraido,pendente,extraindo,erro)", filtro_or)
        self.assertNotIn("validado", filtro_or)
        self.assertNotIn("conciliado", filtro_or)

    # ------------------------------------------------------------------ #
    # Cenário 04 / 07: Bloqueio impeditivo e mensagem orientadora (422)  #
    # ------------------------------------------------------------------ #
    async def test_cenario04_cenario07_bloqueio_data_fora_periodo_retorna_422_mensagem_exata(self):
        """Cenários 04 e 07: Validação defensiva retorna HTTP 422 com formatação DD/MM/YYYY e texto oficial."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-01",
            fonte_pagadora_id="fp-1",
            data_pagamento="2026-10-01",
            mes_ano="2026-09"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            with self.assertRaises(HTTPException) as ctx:
                await _validar_despesa_impl("desp-v156-01", payload, bg_tasks)

            self.assertEqual(ctx.exception.status_code, 422)
            mensagem_esperada = (
                "A data de pagamento (01/10/2026) está fora do período em processamento (2026-09). "
                "Ajuste a data de pagamento para este mês ou exclua a despesa desta pasta mensal para aguardar o fechamento do mês seguinte."
            )
            self.assertEqual(ctx.exception.detail, mensagem_esperada)

    # ------------------------------------------------------------------ #
    # Cenário 05: Desbloqueio e sucesso após correção da data            #
    # ------------------------------------------------------------------ #
    async def test_cenario05_desbloqueio_apos_ajuste_de_data_valida(self):
        """Cenário 05: Ajustando a data para dia válido (2026-09-30), validação conclui com sucesso (status validado)."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-01",
            fonte_pagadora_id="fp-1",
            data_pagamento="2026-09-30",
            mes_ano="2026-09"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await _validar_despesa_impl("desp-v156-01", payload, bg_tasks)
            self.assertTrue(res.ok)
            self.assertEqual(res.status, "validado")

    # ------------------------------------------------------------------ #
    # Cenário 06: Ação direta de exclusão de despesa                     #
    # ------------------------------------------------------------------ #
    async def test_cenario06_exclusao_direta_despesa_pasta_mensal(self):
        """Cenário 06: Exclusão direta remove registro e anexos via DELETE /validacao/despesas/{id}."""
        supabase_mock = MagicMock()
        supabase_mock.table("despesas").select().eq().execute.return_value.data = [{
            "id": "desp-del-156",
            "storage_path": "condos/comprovante_gas.pdf",
            "bucket": "integre"
        }]
        supabase_mock.table("conciliacoes").delete().eq().execute.return_value = MagicMock()
        supabase_mock.storage.from_().remove.return_value = MagicMock()
        supabase_mock.table("despesas").delete().eq().execute.return_value = MagicMock()

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await deletar_despesa("desp-del-156")
            self.assertTrue(res["ok"])
            self.assertEqual(res["id"], "desp-del-156")
            supabase_mock.table("despesas").delete().eq.assert_called_with("id", "desp-del-156")

    # ------------------------------------------------------------------ #
    # Cenário 08: Isolamento estrito por condomínio                      #
    # ------------------------------------------------------------------ #
    @patch("src.api.validacao_router._get_supabase")
    def test_cenario08_isolamento_estrito_por_condominio(self, mock_get_supabase):
        """Cenário 08: O filtro eq(condominio_id, ...) é obrigatório e impede vazamento de despesas de outros condomínios."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        mock_query = self._build_mock_query(return_data=[])
        mock_supabase.table.return_value = mock_query

        response = self.client.get(
            "/api/v1/validacao/despesas?status=todos&condominio_id=cond-especifico-123&mes_ano=2026-09"
        )
        self.assertEqual(response.status_code, 200)

        # O eq("condominio_id", ...) deve ter sido chamado com o id solicitado
        mock_query.eq.assert_any_call("condominio_id", "cond-especifico-123")

    # ------------------------------------------------------------------ #
    # Cenário 09: Despesa com data de pagamento nula                     #
    # ------------------------------------------------------------------ #
    async def test_cenario09_despesa_com_data_pagamento_nula_salva_sem_bloqueio(self):
        """Cenário 09: Despesa com data_pagamento nula permite salvamento e listagem sem erro 422."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="salvar",
            descricao="Nota fiscal sem pagamento registrado",
            data_pagamento=None,
            mes_ano="2026-09"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await _validar_despesa_impl("desp-v156-01", payload, bg_tasks)
            self.assertTrue(res.ok)
