"""
Suite de Testes Automatizados TDD - Release v1.55: Bloqueio de Data de Pagamento Fora da Competência e Calibragem de Threshold Semântico.
Cobertura completa dos cenários BDD 01 a 07 da história STORY-v1.55.
"""

import os
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import BackgroundTasks, HTTPException

from src.services.contexto_service import ContextoService
from src.api.validacao_router import _validar_despesa_impl, deletar_despesa, ValidacaoPayload


class TestV155BloqueioDataPagamento(unittest.IsolatedAsyncioTestCase):
    """Testes da guarda temporal de data_pagamento no endpoint de validação (v1.55)."""

    def _setup_mock_despesa(self, status="extraido"):
        supabase_mock = MagicMock()
        supabase_mock.table("despesas").select().eq().single().execute.return_value.data = {
            "id": "desp-155-01",
            "status": status,
            "condominio_id": "cond-1",
            "administradora_id": "adm-1",
            "sugestao_contabil": {"conta_debito_codigo": "1.1.01"}
        }
        supabase_mock.table("plano_contas").select().eq().eq().execute.return_value.data = [
            {"id": "conta-uuid-01", "codigo_contabil": "1.1.01"}
        ]
        supabase_mock.table("despesas").update().eq().execute.return_value = MagicMock()
        return supabase_mock

    async def test_cenario03_data_pagamento_posterior_a_competencia_retorna_422(self):
        """Cenário 03 / 04: Data de pagamento posterior ao mês ativo (ex: 2026-10-02 em 2026-09) retorna HTTP 422."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-01",
            fonte_pagadora_id="fp-1",
            data_pagamento="2026-10-02",
            mes_ano="2026-09"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            with self.assertRaises(HTTPException) as ctx:
                await _validar_despesa_impl("desp-155-01", payload, bg_tasks)

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("A data de pagamento (02/10/2026) está fora do período em processamento (2026-09)", ctx.exception.detail)
            self.assertIn("Ajuste a data de pagamento para este mês ou exclua a despesa desta pasta mensal para aguardar o fechamento do mês seguinte.", ctx.exception.detail)

    async def test_cenario03_data_pagamento_anterior_a_competencia_retorna_422(self):
        """Cenário 03: Data de pagamento anterior ao mês ativo (ex: 2026-08-30 em 2026-09) retorna HTTP 422."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-01",
            fonte_pagadora_id="fp-1",
            data_pagamento="2026-08-30",
            mes_ano="2026-09"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            with self.assertRaises(HTTPException) as ctx:
                await _validar_despesa_impl("desp-155-01", payload, bg_tasks)

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("A data de pagamento (30/08/2026) está fora do período em processamento (2026-09)", ctx.exception.detail)

    async def test_cenario02_acao_salvar_com_data_divergente_tambem_bloqueia_422(self):
        """Cenário 02: Ação 'salvar' também bloqueia e retorna 422 quando data_pagamento diverge da competência ativa."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="salvar",
            data_pagamento="2026-10-05",
            mes_ano="2026-09"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            with self.assertRaises(HTTPException) as ctx:
                await _validar_despesa_impl("desp-155-01", payload, bg_tasks)

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("05/10/2026", ctx.exception.detail)
            self.assertIn("2026-09", ctx.exception.detail)

    async def test_cenario06_data_dentro_da_competencia_sucesso_retorna_200(self):
        """Cenário 06: Data de pagamento dentro do intervalo do mês ativo (ex: 2026-09-15) processa com sucesso."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-01",
            fonte_pagadora_id="fp-1",
            data_pagamento="2026-09-15",
            mes_ano="2026-09"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await _validar_despesa_impl("desp-155-01", payload, bg_tasks)

            self.assertTrue(res.ok)
            self.assertEqual(res.status, "validado")

    async def test_cenario06_limite_inicio_e_fim_do_mes_permitidos(self):
        """Cenário 06: Primeiro dia (2026-09-01) e último dia (2026-09-30) são estritamente válidos."""
        supabase_mock = self._setup_mock_despesa()

        for dia in ["2026-09-01", "2026-09-30"]:
            bg_tasks = BackgroundTasks()
            payload = ValidacaoPayload(
                acao="confirmar",
                conta_despesa_id="conta-uuid-01",
                fonte_pagadora_id="fp-1",
                data_pagamento=dia,
                mes_ano="2026-09"
            )

            with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
                res = await _validar_despesa_impl("desp-155-01", payload, bg_tasks)
                self.assertTrue(res.ok)

    async def test_cenario07_despesa_sem_data_pagamento_permite_salvar_e_confirmar(self):
        """Cenário 07: Despesa com data_pagamento nula ou vazia não bloqueia salvamento (retrocompatibilidade)."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="salvar",
            descricao="Despesa pendente sem data de quitação",
            data_pagamento=None,
            mes_ano="2026-09"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await _validar_despesa_impl("desp-155-01", payload, bg_tasks)
            self.assertTrue(res.ok)

    async def test_cenario07_mes_ano_omitido_retrocompatibilidade(self):
        """Cenário 07: Requisição sem mes_ano não aplica guarda temporal, permitindo chamadas legadas."""
        supabase_mock = self._setup_mock_despesa()
        bg_tasks = BackgroundTasks()

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-01",
            fonte_pagadora_id="fp-1",
            data_pagamento="2026-11-20",
            mes_ano=None
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await _validar_despesa_impl("desp-155-01", payload, bg_tasks)
            self.assertTrue(res.ok)

    async def test_cenario03_exclusao_direta_despesa(self):
        """Cenário 03: Endpoint de exclusão direta de despesa (DELETE /api/v1/validacao/despesas/{id})."""
        supabase_mock = MagicMock()
        supabase_mock.table("despesas").select().eq().execute.return_value.data = [{
            "id": "desp-del-01",
            "storage_path": "condos/fatura.pdf",
            "bucket": "integre"
        }]
        supabase_mock.table("conciliacoes").delete().eq().execute.return_value = MagicMock()
        supabase_mock.storage.from_().remove.return_value = MagicMock()
        supabase_mock.table("despesas").delete().eq().execute.return_value = MagicMock()

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await deletar_despesa("desp-del-01")

            self.assertTrue(res["ok"])
            self.assertEqual(res["id"], "desp-del-01")
            supabase_mock.table("despesas").delete().eq.assert_called_with("id", "desp-del-01")


class TestV155CalibragemThresholdContexto(unittest.TestCase):
    """Testes da nova calibragem do gatekeeper semântico (threshold 0.65) em ContextoService."""

    def test_cenario04_gatekeeper_cosseno_maior_065_descarta_sem_chamar_llm(self):
        """Cenário 04 / 05: Similaridade de cosseno de 0.68 (> 0.65) descarta atualização sem chamada da LLM."""
        supabase_mock = MagicMock()
        supabase_mock.table().select().eq().eq().execute.return_value.data = [{
            "descricao": "Portaria e Limpeza",
            "contexto": "Serviços especializados de portaria e limpeza predial.",
            "embedding": [0.3] * 768
        }]

        mock_client = MagicMock()
        mock_emb_desc = MagicMock()
        mock_emb_desc.embeddings = [MagicMock(values=[0.3] * 768)]
        mock_client.models.embed_content.return_value = mock_emb_desc

        with patch("google.genai.Client", return_value=mock_client), \
             patch.object(ContextoService, "_cosine_similarity", return_value=0.68):
            sucesso, novo_ctx = ContextoService.atualizar_contexto(
                supabase=supabase_mock,
                admin_id="adm-1",
                codigo_contabil="1.1.02",
                novo_descritivo="Limpeza da guarita e recepção",
                conta_descricao_in="Portaria e Limpeza"
            )

        self.assertFalse(sucesso)
        self.assertIsNone(novo_ctx)
        mock_client.models.generate_content.assert_not_called()
        supabase_mock.table().update.assert_not_called()

    def test_cenario04_gatekeeper_cosseno_menor_065_aciona_llm_e_atualiza(self):
        """Cenário 04 / 05: Similaridade de cosseno de 0.62 (<= 0.65) aciona gemini-3.1-flash-lite e atualiza conta."""
        supabase_mock = MagicMock()
        supabase_mock.table().select().eq().eq().execute.return_value.data = [{
            "descricao": "Segurança Eletrônica",
            "contexto": "Monitoramento de alarmes e controle de acesso biométrico para condomínios.",
            "embedding": [0.2] * 768
        }]

        mock_client = MagicMock()
        mock_emb_desc = MagicMock()
        mock_emb_desc.embeddings = [MagicMock(values=[0.2] * 768)]
        mock_emb_ancorado = MagicMock()
        mock_emb_ancorado.embeddings = [MagicMock(values=[0.4] * 768)]
        mock_client.models.embed_content.side_effect = [mock_emb_desc, mock_emb_ancorado]

        mock_resp = MagicMock()
        mock_resp.text = "Monitoramento de alarmes e manutencao técnica de sistemas de CFTV e controle de acesso predial."
        mock_client.models.generate_content.return_value = mock_resp

        with patch("google.genai.Client", return_value=mock_client), \
             patch.object(ContextoService, "_cosine_similarity", return_value=0.62):
            sucesso, novo_ctx = ContextoService.atualizar_contexto(
                supabase=supabase_mock,
                admin_id="adm-1",
                codigo_contabil="2.2.04",
                novo_descritivo="Reparo de câmeras do circuito fechado de TV",
                conta_descricao_in="Segurança Eletrônica"
            )

        self.assertTrue(sucesso)
        self.assertEqual(novo_ctx, mock_resp.text)
        mock_client.models.generate_content.assert_called_once()
        supabase_mock.table().update.assert_called_once()

    def test_cenario04_gatekeeper_cosseno_exatamente_065_aciona_atualizacao(self):
        """Cenário 04: Ponto de corte estrito: similaridade de exatamente 0.65 aciona atualização (<= 0.65)."""
        supabase_mock = MagicMock()
        supabase_mock.table().select().eq().eq().execute.return_value.data = [{
            "descricao": "Jardinagem",
            "contexto": "Serviços paisagísticos e poda de árvores em áreas externas comuns.",
            "embedding": [0.1] * 768
        }]

        mock_client = MagicMock()
        mock_emb_desc = MagicMock()
        mock_emb_desc.embeddings = [MagicMock(values=[0.1] * 768)]
        mock_emb_ancorado = MagicMock()
        mock_emb_ancorado.embeddings = [MagicMock(values=[0.1] * 768)]
        mock_client.models.embed_content.side_effect = [mock_emb_desc, mock_emb_ancorado]

        mock_resp = MagicMock()
        mock_resp.text = "Serviços de poda de árvores, adubação e manutenção periódica dos jardins prediais."
        mock_client.models.generate_content.return_value = mock_resp

        with patch("google.genai.Client", return_value=mock_client), \
             patch.object(ContextoService, "_cosine_similarity", return_value=0.65):
            sucesso, novo_ctx = ContextoService.atualizar_contexto(
                supabase=supabase_mock,
                admin_id="adm-1",
                codigo_contabil="3.3.01",
                novo_descritivo="Adubação e corte de grama",
                conta_descricao_in="Jardinagem"
            )

        self.assertTrue(sucesso)
        self.assertEqual(novo_ctx, mock_resp.text)
        mock_client.models.generate_content.assert_called_once()
