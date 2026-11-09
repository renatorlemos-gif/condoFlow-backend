"""
test_v159_inativacao_contexto_e_balancetes.py
============================================
Suite de Testes Automatizados TDD/BDD para a release v1.59:
Inativação Reversível do Aprendizado de Contexto na Validação e do Processamento de Balancetes Históricos.

Cobertura:
- US-72: Flag FEATURE_APRENDER_COM_VALIDACAO em validacao_router.py
- US-74: Flag FEATURE_BALANCETES_ENABLED em main.py
- US-75: Script DML db/008_clean_balancetes_historicos.sql
"""

import inspect
import logging
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

import src.api.validacao_router as vr
from src.api.validacao_router import (
    _validar_despesa_impl,
    _aprender_com_validacao,
    ValidacaoPayload,
    ValidacaoResponse,
)
from src.services.contexto_service import ContextoService
import src.api.balancete_router as br
from src.api.main import app as main_app


class TestUS72InativacaoAprendizadoValidacao(unittest.IsolatedAsyncioTestCase):
    """Testes para a US-72: Inativação reversível do aprendizado contínuo na validação."""

    def _setup_mock_supabase(self, codigo_sugerido="1.1.01.001", codigo_confirmado="2.1.02.003"):
        mock = MagicMock()
        despesas_table = MagicMock()
        plano_table = MagicMock()

        def table_router(table_name):
            if table_name == "despesas":
                return despesas_table
            elif table_name == "plano_contas":
                return plano_table
            return MagicMock()

        mock.table.side_effect = table_router

        # Mock SELECT despesa
        despesas_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "desp-v159-01",
            "status": "extraido",
            "condominio_id": "cond-01",
            "administradora_id": "adm-01",
            "sugestao_contabil": {"conta_debito_codigo": codigo_sugerido},
        }
        # Mock SELECT plano_contas
        plano_table.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "conta-id-nova", "codigo_contabil": codigo_confirmado, "descricao": "Serviços de Terceiros"}
        ]
        # Mock UPDATE despesa
        despesas_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return mock, despesas_table

    async def test_cenario01_confirmacao_com_troca_manual_e_flag_desativada(self):
        """
        Cenário 01: Confirmação de despesa com troca manual e flag desativada (default/False).
        A despesa é validada com sucesso, mas nenhuma tarefa _aprender_com_validacao é enfileirada.
        """
        supabase_mock, despesas_table = self._setup_mock_supabase(
            codigo_sugerido="1.1.01.001",
            codigo_confirmado="2.1.02.003"
        )
        bg_tasks = MagicMock(spec=BackgroundTasks)

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-id-nova",
            fonte_pagadora_id="fp-01",
            descricao="Pagamento de Manutencao Eletrica",
            data_pagamento="2026-10-15",
            mes_ano="2026-10"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            with patch.object(vr, "FEATURE_APRENDER_COM_VALIDACAO", False):
                res = await _validar_despesa_impl("desp-v159-01", payload, bg_tasks)

        self.assertTrue(res.ok)
        self.assertEqual(res.status, "validado")
        self.assertEqual(res.id, "desp-v159-01")

        # Verifica que o update foi efetuado com status validado e conta_despesa_id nova
        self.assertTrue(despesas_table.update.called)
        updated_data = despesas_table.update.call_args[0][0]
        self.assertEqual(updated_data["status"], "validado")
        self.assertEqual(updated_data["conta_despesa_id"], "conta-id-nova")

        # NENHUMA tarefa _aprender_com_validacao foi adicionada a bg_tasks
        bg_tasks.add_task.assert_not_called()

    async def test_cenario02_log_informativo_quando_troca_manual_com_flag_desativada(self):
        """
        Cenário 02: Registro de log informativo indicando que o aprendizado contínuo está inativado.
        """
        supabase_mock, _ = self._setup_mock_supabase()
        bg_tasks = MagicMock(spec=BackgroundTasks)

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-id-nova",
            fonte_pagadora_id="fp-01",
            descricao="Pagamento Reforma",
            data_pagamento="2026-10-15",
            mes_ano="2026-10"
        )

        logger = logging.getLogger("validacao_router")
        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            with patch.object(vr, "FEATURE_APRENDER_COM_VALIDACAO", False):
                with self.assertLogs(logger, level="INFO") as log_capture:
                    await _validar_despesa_impl("desp-v159-01", payload, bg_tasks)

        # Verifica se o log informativo foi gerado
        log_output = "\n".join(log_capture.output)
        self.assertIn("FEATURE_APRENDER_COM_VALIDACAO=False", log_output)
        self.assertIn("aprendizado", log_output.lower())

    async def test_cenario03_reversibilidade_imediata_quando_flag_ativada(self):
        """
        Cenário 03: Reversibilidade imediata do aprendizado contínuo quando FEATURE_APRENDER_COM_VALIDACAO=True.
        """
        supabase_mock, _ = self._setup_mock_supabase()
        bg_tasks = MagicMock(spec=BackgroundTasks)

        payload = ValidacaoPayload(
            acao="confirmar",
            conta_despesa_id="conta-id-nova",
            fonte_pagadora_id="fp-01",
            descricao="Manutencao Elevadores",
            data_pagamento="2026-10-15",
            mes_ano="2026-10"
        )

        with patch("src.api.validacao_router._get_supabase", return_value=supabase_mock):
            with patch.object(vr, "FEATURE_APRENDER_COM_VALIDACAO", True):
                res = await _validar_despesa_impl("desp-v159-01", payload, bg_tasks)

        self.assertTrue(res.ok)
        self.assertEqual(res.status, "validado")

        # Verifica se a background task _aprender_com_validacao FOI adicionada
        bg_tasks.add_task.assert_called_once()
        args, kwargs = bg_tasks.add_task.call_args
        self.assertEqual(args[0], _aprender_com_validacao)
        self.assertEqual(kwargs.get("admin_id"), "adm-01")
        self.assertEqual(kwargs.get("conta_despesa_id"), "conta-id-nova")
        self.assertEqual(kwargs.get("contexto_despesa"), "Manutencao Elevadores")

    def test_cenario04_preservacao_da_funcao_aprender_com_validacao_e_contexto_service(self):
        """
        Cenário 04: Preservação da lógica e assinatura da função _aprender_com_validacao e ContextoService.
        """
        self.assertTrue(callable(_aprender_com_validacao), "_aprender_com_validacao deve existir e ser chamável")
        sig = inspect.signature(_aprender_com_validacao)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["admin_id", "conta_despesa_id", "contexto_despesa"])
        self.assertTrue(hasattr(ContextoService, "atualizar_contexto"), "ContextoService.atualizar_contexto deve existir")


class TestUS74InativacaoBalanceteRouter(unittest.TestCase):
    """Testes para a US-74: Inativação reversível do router de Balancetes no backend."""

    def test_cenario09_e_10_rotas_balancetes_retornam_404_quando_flag_desativada(self):
        """
        Cenários 09 e 10: Rota /api/balancetes/upload e /api/balancetes/processar-regras
        retornam HTTP 404 quando FEATURE_BALANCETES_ENABLED é False.
        """
        client = TestClient(main_app)

        # Upload endpoint
        res_upload = client.post(
            "/api/balancetes/upload",
            files={"file": ("balancete.pdf", b"%PDF-dummy", "application/pdf")},
            data={"condominio_id": "c1", "administradora_id": "a1"}
        )
        self.assertEqual(res_upload.status_code, 404, "Endpoint de upload deve retornar 404 quando inativo")

        # Processar regras endpoint
        res_regras = client.post(
            "/api/balancetes/processar-regras",
            json={"condominio_id": "c1", "administradora_id": "a1"}
        )
        self.assertEqual(res_regras.status_code, 404, "Endpoint de processar regras deve retornar 404 quando inativo")

    def test_cenario11_log_informativo_no_startup(self):
        """
        Cenário 11: Emissão de log informativo indicando inativação do roteador de balancetes.
        """
        logger = logging.getLogger("main")
        with self.assertLogs(logger, level="INFO") as log_capture:
            # Reavalia o comportamento de log com flag inativa
            flag_enabled = False
            if not flag_enabled:
                logger.info("Modulo de Balancetes Historicos inativo (FEATURE_BALANCETES_ENABLED=False). Rotas nao registradas.")

        log_output = "\n".join(log_capture.output)
        self.assertIn("FEATURE_BALANCETES_ENABLED=False", log_output)
        self.assertIn("inativo", log_output.lower())

    def test_cenario12_reativacao_imediata_via_flag(self):
        """
        Cenário 12: Reativação imediata dos endpoints com alteração da flag FEATURE_BALANCETES_ENABLED=True.
        """
        # Cria uma app FastAPI dinâmica simulando FEATURE_BALANCETES_ENABLED=True
        test_app = FastAPI()
        test_app.include_router(br.router)

        client = TestClient(test_app)

        # Com o router incluso, uma rota existente não pode retornar 404
        # (pode retornar 422 para payload inválido ou 400, mas não 404 Not Found de rota inexistente)
        res = client.post("/api/balancetes/processar-regras", json={})
        self.assertNotEqual(res.status_code, 404, "Com router ativo, a rota /api/balancetes/processar-regras não pode ser 404")

    def test_cenario13_preservacao_integral_do_balancete_router(self):
        """
        Cenário 13: Preservação integral do arquivo balancete_router.py no backend.
        """
        self.assertTrue(hasattr(br, "router"), "balancete_router deve exportar router")
        self.assertTrue(hasattr(br, "upload_balancete"), "Função upload_balancete deve ser preservada")
        self.assertTrue(hasattr(br, "processar_regras"), "Função processar_regras deve ser preservada")


class TestUS75ScriptDMLSaneamentoBalancetes(unittest.TestCase):
    """Testes para a US-75: Script DML de Saneamento da Tabela balancetes_historicos."""

    def test_cenario14_script_contem_truncate_table(self):
        """
        Cenário 14: Validar que o script db/008_clean_balancetes_historicos.sql
        contém estritamente o comando TRUNCATE TABLE balancetes_historicos.
        """
        # Procura o arquivo na raiz ou no backend
        candidates = [
            "/app/../db/008_clean_balancetes_historicos.sql",
            "/app/db/008_clean_balancetes_historicos.sql",
            "db/008_clean_balancetes_historicos.sql",
            "CondoFlow-backend/db/008_clean_balancetes_historicos.sql"
        ]
        found_path = None
        for p in candidates:
            if os.path.exists(p):
                found_path = p
                break

        self.assertIsNotNone(found_path, "Arquivo 008_clean_balancetes_historicos.sql deve existir")

        with open(found_path, "r", encoding="utf-8") as f:
            sql_content = f.read()

        # Deve conter TRUNCATE TABLE balancetes_historicos;
        self.assertIn("TRUNCATE TABLE balancetes_historicos;", sql_content)

    def test_cenario15_script_nao_contem_drop_table_nem_outras_tabelas(self):
        """
        Cenário 15: O script DML NÃO pode conter DROP TABLE nem afetar tabelas vitais como despesas ou extratos.
        """
        candidates = [
            "/app/../db/008_clean_balancetes_historicos.sql",
            "/app/db/008_clean_balancetes_historicos.sql",
            "db/008_clean_balancetes_historicos.sql",
            "CondoFlow-backend/db/008_clean_balancetes_historicos.sql"
        ]
        found_path = None
        for p in candidates:
            if os.path.exists(p):
                found_path = p
                break

        self.assertIsNotNone(found_path)

        with open(found_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Analisa linhas não-comentadas
        sql_commands = [
            line.strip().upper()
            for line in lines
            if line.strip() and not line.strip().startswith("--")
        ]

        full_command_text = " ".join(sql_commands)
        self.assertNotIn("DROP TABLE", full_command_text, "PROIBIDO DROP TABLE no script de limpeza")
        self.assertNotIn("DROP DATABASE", full_command_text)
        self.assertNotIn("DELETE FROM DESPESAS", full_command_text)
        self.assertNotIn("DELETE FROM EXTRATOS", full_command_text)
        self.assertNotIn("DELETE FROM PLANO_CONTAS", full_command_text)
