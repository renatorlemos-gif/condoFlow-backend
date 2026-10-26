"""
Suite de Testes Automatizados TDD - Release v1.53: Otimizacao Semantica do Contexto Contabil.
Cobertura de 100% dos 16 cenarios BDD das historias US-01 a US-04.
"""

import os
import json
import inspect
import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from fastapi import BackgroundTasks
from google.genai.errors import APIError

from src.services.contexto_service import ContextoService
from src.api.validacao_router import _validar_despesa_impl, ValidacaoPayload
from src.api.balancete_router import processar_regras, ProcessarRegrasRequest
from scripts.sanear_contextos_plano_contas import parse_args, SaneadorContextos


class TestUS01ContextoService(unittest.TestCase):
    """US-01: Engenharia de Prompt e Sintese Concisa de Contexto Contabil no ContextoService."""

    def test_us01_cenario01_criacao_nova_conta_ancoragem_e_faixa_tamanho(self):
        """Cenario 01: Geracao de contexto inicial para nova conta na faixa [80, 140] chars e ancoragem."""
        supabase_mock = MagicMock()
        supabase_mock.table().select().eq().eq().execute.return_value.data = []

        mock_client = MagicMock()
        mock_resp = MagicMock()
        # Texto gerado de 95 caracteres (dentro de [80, 140])
        mock_resp.text = "Manutencao preventiva e corretiva especializada no sistema hidraulico e bombas de recalque."
        self.assertTrue(80 <= len(mock_resp.text) <= 140)
        mock_client.models.generate_content.return_value = mock_resp

        mock_emb_res = MagicMock()
        mock_emb = MagicMock()
        mock_emb.values = [0.1] * 768
        mock_emb_res.embeddings = [mock_emb]
        mock_client.models.embed_content.return_value = mock_emb_res

        with patch("google.genai.Client", return_value=mock_client):
            sucesso, novo_ctx = ContextoService.atualizar_contexto(
                supabase=supabase_mock,
                admin_id="adm-123",
                codigo_contabil="1.2.03",
                novo_descritivo="Revisao preventiva das bombas de recalque do subsolo",
                conta_descricao_in="Manutencao de Bombas D'Agua"
            )

        self.assertTrue(sucesso)
        self.assertEqual(novo_ctx, mock_resp.text)
        self.assertTrue(80 <= len(novo_ctx) <= 140)

        # Valida que o prompt continha '80 e 140 caracteres'
        call_prompt = mock_client.models.generate_content.call_args[1]["contents"][0]
        self.assertIn("80 e 140 caracteres", call_prompt)
        self.assertIn("PROIBICAO TAXATIVA", call_prompt)

        # Valida ancoragem de titulo
        ancoragem_esperada = f"Manutencao de Bombas D'Agua - {mock_resp.text}"
        call_emb_text = mock_client.models.embed_content.call_args[1]["contents"]
        self.assertEqual(call_emb_text, ancoragem_esperada)

        # Valida persistencia com criada_por_ia = True
        supabase_mock.table().insert.assert_called_once()
        insert_payload = supabase_mock.table().insert.call_args[0][0]
        self.assertTrue(insert_payload.get("criada_por_ia"))
        self.assertEqual(len(insert_payload.get("embedding")), 768)

    def test_us01_cenario02_inspecao_prompts_rejeicao_termos_genericos(self):
        """Cenario 02: Rejeicao rigida de termos genericos e guarda-chuva no prompt do ContextoService."""
        source = inspect.getsource(ContextoService.atualizar_contexto)
        
        self.assertIn("80 e 140 caracteres", source)
        self.assertIn("PROIBICAO TAXATIVA", source)
        self.assertIn("despesas operacionais gerais", source)
        self.assertIn("servicos diversos", source)
        self.assertIn("manutencao predial ampla", source)
        self.assertIn("gastos rotineiros", source)
        self.assertIn("taxas administrativas", source)
        self.assertIn("REGRA CRITICA: Voce deve GENERALIZAR o conteudo", source)

    def test_us01_cenario03_incorporacao_incremental_cosseno_menor_ou_igual_70(self):
        """Cenario 03: Incorporacao incremental condensada quando similaridade <= 0.65."""
        supabase_mock = MagicMock()
        # Conta existente com contexto e embedding
        supabase_mock.table().select().eq().eq().execute.return_value.data = [{
            "descricao": "Elevadores",
            "contexto": "Manutencao tecnica preventiva e reparos periodicos em elevadores prediais.",
            "embedding": [0.1] * 768
        }]

        mock_client = MagicMock()
        
        # Similaridade calculada simulando 0.60 (<= 0.65)
        # Mock do embed_content para novo_descritivo e para ancoragem
        mock_emb_desc = MagicMock()
        mock_emb_desc.embeddings = [MagicMock(values=[0.2] * 768)]
        
        mock_emb_ancorado = MagicMock()
        mock_emb_ancorado.embeddings = [MagicMock(values=[0.3] * 768)]
        
        mock_client.models.embed_content.side_effect = [mock_emb_desc, mock_emb_ancorado]

        mock_resp = MagicMock()
        mock_resp.text = "Manutencao preventiva e reparos periodicos em cabos de tracao e componentes de elevadores prediais."
        mock_client.models.generate_content.return_value = mock_resp

        with patch("google.genai.Client", return_value=mock_client), \
             patch.object(ContextoService, "_cosine_similarity", return_value=0.60):
            sucesso, novo_ctx = ContextoService.atualizar_contexto(
                supabase=supabase_mock,
                admin_id="adm-123",
                codigo_contabil="2.1.08",
                novo_descritivo="Substituicao emergencial de cabos de tracao",
                conta_descricao_in="Elevadores"
            )

        self.assertTrue(sucesso)
        self.assertEqual(novo_ctx, mock_resp.text)
        self.assertTrue(80 <= len(novo_ctx) <= 140)
        mock_client.models.generate_content.assert_called_once()
        supabase_mock.table().update.assert_called_once()

    def test_us01_cenario04_gatekeeper_cosseno_maior_70_descarta_sem_chamar_llm(self):
        """Cenario 04: Gatekeeper de cosseno > 0.65 descarta atualizacao sem chamada de LLM."""
        supabase_mock = MagicMock()
        supabase_mock.table().select().eq().eq().execute.return_value.data = [{
            "descricao": "Energia Eletrica",
            "contexto": "Consumo de energia eletrica fornecida pela concessionaria publica para areas comuns.",
            "embedding": [0.5] * 768
        }]

        mock_client = MagicMock()
        mock_emb_desc = MagicMock()
        mock_emb_desc.embeddings = [MagicMock(values=[0.5] * 768)]
        mock_client.models.embed_content.return_value = mock_emb_desc

        with patch("google.genai.Client", return_value=mock_client), \
             patch.object(ContextoService, "_cosine_similarity", return_value=0.68):
            sucesso, novo_ctx = ContextoService.atualizar_contexto(
                supabase=supabase_mock,
                admin_id="adm-123",
                codigo_contabil="3.1.01",
                novo_descritivo="Conta de luz do mes atual",
                conta_descricao_in="Energia Eletrica"
            )

        self.assertFalse(sucesso)
        self.assertIsNone(novo_ctx)
        # Nao deve chamar o modelo de texto
        mock_client.models.generate_content.assert_not_called()
        supabase_mock.table().update.assert_not_called()


class TestUS02ValidacaoRouter(unittest.IsolatedAsyncioTestCase):
    """US-02: Gatilho de Aprendizado Condicional Exclusivo por Divergencia Manual na Validacao."""

    async def test_us02_cenario01_confirmar_com_aceite_sugestao_dispensa_aprendizado(self):
        """Cenario 01: Confirmacao com aceite da sugestao da IA dispensa background task de aprendizado."""
        supabase_mock = MagicMock()

        # Despesa existente com sugestao_contabil conta_debito_codigo = "1.1.05"
        supabase_mock.table("despesas").select().eq().single().execute.return_value.data = {
            "id": "desp-01",
            "status": "extraido",
            "condominio_id": "cond-1",
            "administradora_id": "adm-1",
            "sugestao_contabil": {"conta_debito_codigo": "1.1.05"}
        }

        # Conta confirmada pelo usuario coincide com o codigo sugerido "1.1.05"
        supabase_mock.table("plano_contas").select().eq().eq().execute.return_value.data = [
            {"id": "conta-uuid-01", "codigo_contabil": "1.1.05"}
        ]

        bg_tasks = BackgroundTasks()
        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-01",
            fonte_pagadora_id="fp-1",
            descricao="Tarifa bancaria",
            fornecedor="Banco"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await _validar_despesa_impl("desp-01", payload, bg_tasks)

        self.assertTrue(res.ok)
        self.assertEqual(res.status, "validado")
        # Nao deve enfileirar tarefa de aprendizado
        self.assertEqual(len(bg_tasks.tasks), 0)

    async def test_us02_cenario02_confirmar_com_troca_manual_dispara_aprendizado(self):
        """Cenario 02: Confirmacao com troca manual de conta dispara aprendizado em background."""
        supabase_mock = MagicMock()

        # Despesa sugerida para "2.1.01"
        supabase_mock.table("despesas").select().eq().single().execute.return_value.data = {
            "id": "desp-02",
            "status": "extraido",
            "condominio_id": "cond-1",
            "administradora_id": "adm-1",
            "sugestao_contabil": {"conta_debito_codigo": "2.1.01"}
        }

        # Usuario alterou manualmente para "2.1.08"
        supabase_mock.table("plano_contas").select().eq().eq().execute.return_value.data = [
            {"id": "conta-uuid-elevadores", "codigo_contabil": "2.1.08"}
        ]

        bg_tasks = BackgroundTasks()
        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-elevadores",
            fonte_pagadora_id="fp-1",
            descricao="Reparo de botoeira do elevador social",
            fornecedor="Otis"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await _validar_despesa_impl("desp-02", payload, bg_tasks)

        self.assertTrue(res.ok)
        self.assertEqual(res.status, "validado")
        # Deve enfileirar tarefa assincrona de aprendizado
        self.assertEqual(len(bg_tasks.tasks), 1)
        task = bg_tasks.tasks[0]
        self.assertEqual(task.kwargs.get("admin_id"), "adm-1")
        self.assertEqual(task.kwargs.get("conta_despesa_id"), "conta-uuid-elevadores")

    async def test_us02_cenario03_confirmar_sem_sugestao_previa_dispara_aprendizado(self):
        """Cenario 03: Despesa sem sugestao previa dispara aprendizado como nova classificacao."""
        supabase_mock = MagicMock()

        # Despesa sem sugestao_contabil (None)
        supabase_mock.table("despesas").select().eq().single().execute.return_value.data = {
            "id": "desp-03",
            "status": "extraido",
            "condominio_id": "cond-1",
            "administradora_id": "adm-1",
            "sugestao_contabil": None
        }

        supabase_mock.table("plano_contas").select().eq().eq().execute.return_value.data = [
            {"id": "conta-uuid-nova", "codigo_contabil": "3.2.01"}
        ]

        bg_tasks = BackgroundTasks()
        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-uuid-nova",
            fonte_pagadora_id="fp-1",
            descricao="Laudo de vistoria predial",
            fornecedor="Engenharia Ltda"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            res = await _validar_despesa_impl("desp-03", payload, bg_tasks)

        self.assertTrue(res.ok)
        self.assertEqual(res.status, "validado")
        # Deve enfileirar aprendizado pois not conta_sugerida_codigo
        self.assertEqual(len(bg_tasks.tasks), 1)

    async def test_us02_cenario04_salvar_ou_cancelar_nao_dispara_aprendizado(self):
        """Cenario 04: Acao de salvar rascunho ou cancelar nunca dispara tarefa de aprendizado."""
        supabase_mock = MagicMock()
        supabase_mock.table("despesas").select().eq().single().execute.return_value.data = {
            "id": "desp-04",
            "status": "extraido",
            "condominio_id": "cond-1",
            "administradora_id": "adm-1",
            "sugestao_contabil": {"conta_debito_codigo": "1.1.01"}
        }

        for acao in ["salvar", "cancelar"]:
            bg_tasks = BackgroundTasks()
            payload = ValidacaoPayload(
                acao=acao,
                conta_despesa_id="conta-uuid-qualquer",
                descricao="Despesa em rascunho"
            )

            with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
                res = await _validar_despesa_impl("desp-04", payload, bg_tasks)

            self.assertTrue(res.ok)
            self.assertEqual(len(bg_tasks.tasks), 0)


class TestUS03BalanceteRouter(unittest.IsolatedAsyncioTestCase):
    """US-03: Processamento e Atualizacao Consistente de Contexto em Lotes de Balancetes Historicos."""

    def _setup_mock_supabase(self, lancamentos_data):
        mock_supabase = MagicMock()
        table_mock = MagicMock()
        mock_supabase.table.return_value = table_mock

        query_mock = MagicMock()
        query_mock.execute.return_value.data = lancamentos_data
        query_mock.or_.return_value = query_mock
        query_mock.eq.return_value = query_mock
        table_mock.select.return_value = query_mock

        update_mock = MagicMock()
        update_in_mock = MagicMock()
        update_in_mock.execute.return_value = MagicMock()
        update_mock.in_.return_value = update_in_mock
        table_mock.update.return_value = update_mock

        return mock_supabase, table_mock, query_mock, update_mock

    async def test_us03_cenario01_agrupamento_nova_conta_sucesso_sintese(self):
        """Cenario 01: Nova conta do balancete gera contexto conciso e atualiza processado_ia."""
        dados = [
            {
                "id": f"bal-{i}",
                "administradora_id": "adm-1",
                "codigo_contabil": "1.1.10",
                "conta_descricao": "Consumo de Gas Canalizado",
                "descricao_lancamento": f"Comgas fatura {i}"
            }
            for i in range(15)
        ]
        mock_supabase, table_mock, _, update_mock = self._setup_mock_supabase(dados)

        with patch.dict(os.environ, {"SUPABASE_URL": "http://mock", "SUPABASE_SERVICE_KEY": "key", "GEMINI_API_KEY": "gkey"}), \
             patch("src.api.balancete_router.create_client", return_value=mock_supabase), \
             patch("src.services.contexto_service.ContextoService.atualizar_contexto", return_value=(True, "Fornecimento continuado de gas encanado para sistema de aquecimento predial.")), \
             patch("asyncio.sleep", new_callable=AsyncMock):

            resp = await processar_regras(ProcessarRegrasRequest(administradora_id="adm-1"))

        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["processados"], 1)
        self.assertEqual(resp["erros"], 0)
        self.assertEqual(len(resp["detalhes"]), 1)
        self.assertEqual(resp["detalhes"][0]["conta"], "1.1.10")

        # Verifica que marcou processado_ia = True
        table_mock.update.assert_called_with({"processado_ia": True})

    async def test_us03_cenario02_descarte_legitimo_cosseno_maior_70_marca_processado_sem_erro(self):
        """Cenario 02: Descarte legitimo de conta ja conhecida (> 0.65) marca processado_ia sem gerar erro."""
        dados = [
            {
                "id": "bal-conhecido-1",
                "administradora_id": "adm-1",
                "codigo_contabil": "2.1.01",
                "conta_descricao": "Manutencao Predial",
                "descricao_lancamento": "Reparo eletrico comum"
            }
        ]
        mock_supabase, table_mock, _, _ = self._setup_mock_supabase(dados)

        # ContextoService retorna (False, None) por gatekeeper de similaridade > 0.65
        with patch.dict(os.environ, {"SUPABASE_URL": "http://mock", "SUPABASE_SERVICE_KEY": "key", "GEMINI_API_KEY": "gkey"}), \
             patch("src.api.balancete_router.create_client", return_value=mock_supabase), \
             patch("src.services.contexto_service.ContextoService.atualizar_contexto", return_value=(False, None)), \
             patch("asyncio.sleep", new_callable=AsyncMock):

            resp = await processar_regras(ProcessarRegrasRequest(administradora_id="adm-1"))

        self.assertEqual(resp["status"], "success")
        # Nao deve computar como erro!
        self.assertEqual(resp["erros"], 0)
        # Deve ter atualizado processado_ia para True nos lancamentos
        table_mock.update.assert_called_with({"processado_ia": True})

    async def test_us03_cenario03_incorporacao_incremental_balancete_cosseno_menor_70(self):
        """Cenario 03: Incorporacao incremental de lancamentos de balancete com similaridade <= 0.65."""
        dados = [
            {
                "id": "bal-inc-1",
                "administradora_id": "adm-1",
                "codigo_contabil": "3.1.02",
                "conta_descricao": "Conservacao",
                "descricao_lancamento": "Polimento de piso de marmore"
            }
        ]
        mock_supabase, table_mock, _, _ = self._setup_mock_supabase(dados)

        with patch.dict(os.environ, {"SUPABASE_URL": "http://mock", "SUPABASE_SERVICE_KEY": "key", "GEMINI_API_KEY": "gkey"}), \
             patch("src.api.balancete_router.create_client", return_value=mock_supabase), \
             patch("src.services.contexto_service.ContextoService.atualizar_contexto", return_value=(True, "Servicos periodicos de conservacao, limpeza tecnica e tratamento de pisos.")), \
             patch("asyncio.sleep", new_callable=AsyncMock):

            resp = await processar_regras(ProcessarRegrasRequest(administradora_id="adm-1"))

        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["erros"], 0)
        self.assertEqual(len(resp["detalhes"]), 1)
        self.assertEqual(resp["detalhes"][0]["conta"], "3.1.02")

    async def test_us03_cenario04_chunks_update_120_registros_e_tratamento_excecao(self):
        """Cenario 04: Atualizacao de 120 registros em chunks de 50 e incremento de erros apenas em falha real."""
        dados = [
            {
                "id": f"bal-chunk-{i}",
                "administradora_id": "adm-1",
                "codigo_contabil": "4.1.01",
                "conta_descricao": "Portaria Remota",
                "descricao_lancamento": f"Lancamento {i}"
            }
            for i in range(120)
        ]
        mock_supabase, table_mock, _, update_mock = self._setup_mock_supabase(dados)

        update_calls = []
        def track_in(field, values):
            update_calls.append(len(values))
            mock_sub = MagicMock()
            mock_sub.execute.return_value = MagicMock()
            return mock_sub

        update_mock.in_.side_effect = track_in

        with patch.dict(os.environ, {"SUPABASE_URL": "http://mock", "SUPABASE_SERVICE_KEY": "key", "GEMINI_API_KEY": "gkey"}), \
             patch("src.api.balancete_router.create_client", return_value=mock_supabase), \
             patch("src.services.contexto_service.ContextoService.atualizar_contexto", return_value=(True, "Servicos de portaria remota e controle de acesso eletronico.")), \
             patch("asyncio.sleep", new_callable=AsyncMock):

            resp = await processar_regras(ProcessarRegrasRequest(administradora_id="adm-1"))

        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["erros"], 0)
        # Chunks esperados para 120 itens: 50, 50, 20
        self.assertEqual(update_calls, [50, 50, 20])


class TestUS04ScriptSaneamento(unittest.IsolatedAsyncioTestCase):
    """US-04: Script CLI de Saneamento e Re-vetorizacao Retroativa no Supabase."""

    def test_us04_cenario01_parser_argumentos_cli(self):
        """Cenario 01: Suporte aos argumentos CLI do script de saneamento."""
        args1 = parse_args(["--administradora-id", "uuid-adm-1", "--limite-chars", "120", "--todas", "--dry-run"])
        self.assertEqual(args1.administradora_id, "uuid-adm-1")
        self.assertEqual(args1.limite_chars, 120)
        self.assertTrue(args1.todas)
        self.assertTrue(args1.dry_run)

        # Defaults
        args2 = parse_args([])
        self.assertIsNone(args2.administradora_id)
        self.assertEqual(args2.limite_chars, 140)
        self.assertFalse(args2.todas)
        self.assertFalse(args2.dry_run)

    async def test_us04_cenario01_varredura_padrao_saneamento_contas_prolixas(self):
        """Cenario 01: Varredura padrao e saneamento de contas > 140 chars mantendo as demais intocadas."""
        mock_supabase = MagicMock()
        mock_supabase.table("plano_contas").select().execute.return_value.data = [
            {
                "id": "c-prolixa-1",
                "codigo_contabil": "2.1.04",
                "descricao": "Seguro Predial",
                # 250 caracteres (prolixo)
                "contexto": "Despesas operacionais gerais voltadas para apolices de seguro predial obrigatorio contra incendios, sinistros diversos, responsabilidade civil e despesas rotineiras de protecao patrimonial para cobertura de imprevistos estruturais do condominio edilicio."
            },
            {
                "id": "c-curta-2",
                "codigo_contabil": "1.1.02",
                "descricao": "Agua e Esgoto",
                # 95 caracteres (conciso)
                "contexto": "Fornecimento de agua potavel e coleta de esgoto sanitario pela concessionaria publica de saneamento."
            }
        ]

        mock_gemini = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Apolice de seguro predial obrigatorio contra incendio, sinistros e responsabilidade civil do condominio."
        mock_gemini.models.generate_content.return_value = mock_resp

        mock_emb_res = MagicMock()
        mock_emb_res.embeddings = [MagicMock(values=[0.1] * 768)]
        mock_gemini.models.embed_content.return_value = mock_emb_res

        saneador = SaneadorContextos(mock_supabase, mock_gemini)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            rel = await saneador.executar(limite_chars=140, todas=False, dry_run=False)

        self.assertEqual(rel["total_analisadas"], 2)
        self.assertEqual(rel["saneadas"], 1)
        self.assertEqual(rel["ignoradas"], 1)
        self.assertEqual(rel["erros"], 0)

        # Valida update no Supabase apenas para a conta prolixa
        mock_supabase.table("plano_contas").update.assert_called_once()
        update_call = mock_supabase.table("plano_contas").update.call_args[0][0]
        self.assertEqual(update_call["contexto"], mock_resp.text)
        self.assertEqual(len(update_call["embedding"]), 768)

    async def test_us04_cenario02_modo_dry_run_nao_modifica_supabase_nem_chama_ia(self):
        """Cenario 02: Modo Dry-Run lista contas elegiveis sem chamar Gemini nem gravar no Supabase."""
        mock_supabase = MagicMock()
        mock_supabase.table("plano_contas").select().execute.return_value.data = [
            {
                "id": "c-1",
                "codigo_contabil": "2.1.04",
                "descricao": "Elevadores",
                "contexto": "Texto prolixo com mais de cento e quarenta caracteres para demonstrar que o modo de simulacao identifica a conta mas nao executa operacoes de escrita no Supabase."
            }
        ]
        mock_gemini = MagicMock()

        saneador = SaneadorContextos(mock_supabase, mock_gemini)
        rel = await saneador.executar(limite_chars=140, todas=False, dry_run=True)

        self.assertEqual(rel["saneadas"], 1)
        mock_gemini.models.generate_content.assert_not_called()
        mock_gemini.models.embed_content.assert_not_called()
        mock_supabase.table("plano_contas").update.assert_not_called()

    async def test_us04_cenario03_idempotencia_e_retomada_segura(self):
        """Cenario 03: Idempotencia - contas ja saneadas (<= 140) sao ignoradas em reexecucao."""
        mock_supabase = MagicMock()
        # Todas as contas já possuem <= 140 chars
        mock_supabase.table("plano_contas").select().execute.return_value.data = [
            {"id": "c-1", "codigo_contabil": "1.1.01", "descricao": "Conta 1", "contexto": "Contexto conciso de 90 caracteres para validar a retomada segura e idempotencia do processo."},
            {"id": "c-2", "codigo_contabil": "1.1.02", "descricao": "Conta 2", "contexto": "Outro contexto perfeitamente saneado com 88 caracteres sem qualquer jargao generico ou amplo."}
        ]
        mock_gemini = MagicMock()

        saneador = SaneadorContextos(mock_supabase, mock_gemini)
        rel = await saneador.executar(limite_chars=140, todas=False, dry_run=False)

        self.assertEqual(rel["saneadas"], 0)
        self.assertEqual(rel["ignoradas"], 2)
        mock_gemini.models.generate_content.assert_not_called()
        mock_supabase.table("plano_contas").update.assert_not_called()

    async def test_us04_cenario04_rate_limit_com_backoff_exponencial(self):
        """Cenario 04: Tratamento de Rate Limit (HTTP 429) com retry e backoff exponencial."""
        mock_supabase = MagicMock()
        mock_gemini = MagicMock()

        # Falha 429 na primeira chamada, sucesso na segunda
        mock_gemini.models.generate_content.side_effect = [
            APIError(429, {"error": {"code": 429, "message": "RESOURCE_EXHAUSTED"}}),
            MagicMock(text="Contexto sintetizado apos retentativa com sucesso na segunda chamada.")
        ]
        mock_gemini.models.embed_content.return_value.embeddings = [MagicMock(values=[0.1] * 768)]

        saneador = SaneadorContextos(mock_supabase, mock_gemini)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            novo_ctx, novo_emb = await saneador.sintetizar_e_vetorizar_com_backoff(
                descricao="Elevadores",
                contexto_antigo="Texto prolixo antigo..."
            )

        self.assertIn("apos retentativa", novo_ctx)
        self.assertEqual(len(novo_emb), 768)
        # Sleep de backoff chamado (5s para primeira falha)
        mock_sleep.assert_called_with(5.0)


if __name__ == "__main__":
    unittest.main()
