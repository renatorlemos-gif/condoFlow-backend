"""
test_v158_cadastro_despesa_manual.py
====================================
Suíte de Testes Automatizados TDD para a Release v1.58:
Cadastro de Despesa Manual na Conciliação Bancária Agrupada e Individual.

Cobertura:
- US-01: Endpoint POST /api/v1/despesas/manual
  * Cenário 01: Criação bem-sucedida de despesa manual válida (HTTP 201)
  * Cenário 02: Bloqueio estrito com HTTP 422 quando data_pagamento diverge da competência (formatos MM/YYYY e YYYY-MM)
  * Cenário 03: Rejeição com HTTP 422 para valor_total menor ou igual a zero (0.00 e -15.50)
  * Cenário 04: Rejeição com HTTP 404 para conta de despesa inexistente ou pertencente a outra administradora
  * Cenário 05: Rejeição com HTTP 404 para fonte pagadora inexistente ou vinculada a outro condomínio
  * Cenário 06: Criação bem-sucedida omitindo o campo fornecedor opcional
  * Validação de Descrição vazia ou somente espaços em branco (HTTP 422)
- US-04: Robustez de Estorno e Não-Regressão no Fechamento Contábil
  * Cenário 18: Estorno de conciliação com despesa manual reverte status para "validado"
  * Cenário 19: Despesa desfeita volta a ser listada na modal de despesas disponíveis (busca com filtro)
  * Cenário 20: Exportação contábil Alterdata inclui despesa manual com partida dobrada íntegra
  * Cenário 21: Consulta de despesa manual sem arquivo físico retorna foto_url nula com segurança
"""

import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.services.exportador_service import ExportadorService


class TestV158CadastroDespesaManual(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.condominio_id = "c8e2a392-5cb1-4f10-b984-72183c271e89"
        self.administradora_id = "1"
        self.conta_despesa_id = "a12d9b64-28b3-4f91-88df-65829e02fb41"
        self.fonte_pagadora_id = "77bb3241-118f-43ea-98be-8fca55490072"

    def _payload_valido(self, **overrides):
        base = {
            "condominio_id": self.condominio_id,
            "administradora_id": self.administradora_id,
            "data_pagamento": "2026-09-30",
            "competencia": "09/2026",
            "valor_total": 89.90,
            "conta_despesa_id": self.conta_despesa_id,
            "fonte_pagadora_id": self.fonte_pagadora_id,
            "descricao": "Tarifa Pacote de Serviços Bancários - C/C Itaú",
            "fornecedor": "Banco Itaú S.A.",
        }
        base.update(overrides)
        return base

    def _configurar_mock_supabase(self, mock_get_supabase, conta_valida=True, conta_adm="1",
                                   fonte_valida=True, fonte_condo="c8e2a392-5cb1-4f10-b984-72183c271e89"):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        def table_side_effect(table_name):
            query = MagicMock()
            query.select.return_value = query
            query.eq.return_value = query
            query.order.return_value = query
            query.limit.return_value = query
            query.in_.return_value = query
            query.single.return_value = query
            query.delete.return_value = query
            query.update.return_value = query

            if table_name == "plano_contas":
                if conta_valida:
                    query.execute.return_value = MagicMock(
                        data=[{"id": self.conta_despesa_id, "administradora_id": conta_adm}]
                    )
                else:
                    query.execute.return_value = MagicMock(data=[])
                return query

            elif table_name == "fontes_pagadoras":
                if fonte_valida:
                    query.execute.return_value = MagicMock(
                        data=[{"id": self.fonte_pagadora_id, "condominio_id": fonte_condo}]
                    )
                else:
                    query.execute.return_value = MagicMock(data=[])
                return query

            elif table_name == "despesas":
                def fake_insert(record):
                    insert_query = MagicMock()
                    inserted_row = {
                        "id": "f3c8340d-327c-40ea-9e32-23c4a6311689",
                        **record
                    }
                    insert_query.execute.return_value = MagicMock(data=[inserted_row])
                    return insert_query
                query.insert.side_effect = fake_insert
                query.execute.return_value = MagicMock(data=[])
                return query

            return query

        mock_supabase.table.side_effect = table_side_effect
        return mock_supabase

    # ================================================================= #
    #  US-01: Cenários 01 a 06                                           #
    # ================================================================= #

    @patch("src.api.despesa_router._get_supabase")
    def test_cenario01_criacao_bem_sucedida_despesa_manual_valida(self, mock_get_supabase):
        """Cenário 01: Criação bem-sucedida de despesa manual válida (HTTP 201)."""
        self._configurar_mock_supabase(mock_get_supabase)
        payload = self._payload_valido()

        response = self.client.post("/api/v1/despesas/manual", json=payload)

        self.assertEqual(response.status_code, 201)
        data = response.json()

        self.assertEqual(data["status"], "validado")
        self.assertEqual(data["numero_doc"], "S/DOC")
        self.assertTrue(data["sem_comprovante"])
        self.assertEqual(data["tipo_origem"], "manual_extrato")
        self.assertIsNone(data["storage_path"])
        self.assertIsNone(data["bucket"])
        self.assertEqual(data["data_pagamento"], "2026-09-30")
        self.assertEqual(data["data_emissao"], "2026-09-30")
        self.assertEqual(data["descricao"], "Tarifa Pacote de Serviços Bancários - C/C Itaú")
        self.assertEqual(data["descricao_original"], "Tarifa Pacote de Serviços Bancários - C/C Itaú")
        self.assertEqual(data["valor_total"], 89.90)
        self.assertTrue(data["filename"].startswith("manual_"))
        self.assertTrue(data["filename"].endswith(".pdf"))
        self.assertIn("criado_em", data)
        self.assertIn("extraido_em", data)

    @patch("src.api.despesa_router._get_supabase")
    def test_cenario02_bloqueio_data_pagamento_diverge_da_competencia(self, mock_get_supabase):
        """Cenário 02: Bloqueio estrito com HTTP 422 quando data_pagamento diverge da competência."""
        self._configurar_mock_supabase(mock_get_supabase)

        # Caso A: competência 09/2026 e data 2026-10-02 (mês seguinte)
        payload_a = self._payload_valido(
            competencia="09/2026",
            data_pagamento="2026-10-02"
        )
        response_a = self.client.post("/api/v1/despesas/manual", json=payload_a)
        self.assertEqual(response_a.status_code, 422)
        detalhe_a = response_a.json()["detail"]
        self.assertEqual(
            detalhe_a,
            "A data de pagamento (02/10/2026) está fora do período em processamento (09/2026). Ajuste a data para este mês ou altere a competência."
        )

        # Caso B: formato YYYY-MM ("2026-09") e data 2026-08-31 (mês anterior)
        payload_b = self._payload_valido(
            competencia="2026-09",
            data_pagamento="2026-08-31"
        )
        response_b = self.client.post("/api/v1/despesas/manual", json=payload_b)
        self.assertEqual(response_b.status_code, 422)
        detalhe_b = response_b.json()["detail"]
        self.assertEqual(
            detalhe_b,
            "A data de pagamento (31/08/2026) está fora do período em processamento (09/2026). Ajuste a data para este mês ou altere a competência."
        )

        # Caso C: mesmo mês mas outro ano (2025 vs 2026)
        payload_c = self._payload_valido(
            competencia="09/2026",
            data_pagamento="2025-09-15"
        )
        response_c = self.client.post("/api/v1/despesas/manual", json=payload_c)
        self.assertEqual(response_c.status_code, 422)

    def test_cenario03_rejeicao_valor_total_nao_positivo(self):
        """Cenário 03: Rejeição com erro de validação para valor total menor ou igual a zero."""
        # Caso A: valor zero (0.00)
        payload_zero = self._payload_valido(valor_total=0.00)
        resp_zero = self.client.post("/api/v1/despesas/manual", json=payload_zero)
        self.assertEqual(resp_zero.status_code, 422)

        # Caso B: valor negativo (-15.50)
        payload_neg = self._payload_valido(valor_total=-15.50)
        resp_neg = self.client.post("/api/v1/despesas/manual", json=payload_neg)
        self.assertEqual(resp_neg.status_code, 422)

    @patch("src.api.despesa_router._get_supabase")
    def test_cenario04_rejeicao_conta_despesa_inexistente_ou_outra_adm(self, mock_get_supabase):
        """Cenário 04: Rejeição com HTTP 404 para conta de despesa inexistente ou de outra administradora."""
        # Caso A: conta não existe na tabela plano_contas
        self._configurar_mock_supabase(mock_get_supabase, conta_valida=False)
        payload = self._payload_valido()
        resp_inexistente = self.client.post("/api/v1/despesas/manual", json=payload)
        self.assertEqual(resp_inexistente.status_code, 404)
        self.assertIn("Conta contábil de despesa não encontrada", resp_inexistente.json()["detail"])

        # Caso B: conta pertence a outra administradora (ex: adm "999" vs payload "1")
        self._configurar_mock_supabase(mock_get_supabase, conta_valida=True, conta_adm="999")
        resp_outra_adm = self.client.post("/api/v1/despesas/manual", json=payload)
        self.assertEqual(resp_outra_adm.status_code, 404)
        self.assertIn("Conta contábil de despesa não encontrada", resp_outra_adm.json()["detail"])

    @patch("src.api.despesa_router._get_supabase")
    def test_cenario05_rejeicao_fonte_pagadora_inexistente_ou_outro_condo(self, mock_get_supabase):
        """Cenário 05: Rejeição com HTTP 404 para fonte pagadora inexistente ou de outro condomínio."""
        # Caso A: fonte não existe na tabela fontes_pagadoras
        self._configurar_mock_supabase(mock_get_supabase, fonte_valida=False)
        payload = self._payload_valido()
        resp_inexistente = self.client.post("/api/v1/despesas/manual", json=payload)
        self.assertEqual(resp_inexistente.status_code, 404)
        self.assertIn("Fonte pagadora não encontrada", resp_inexistente.json()["detail"])

        # Caso B: fonte pertence a outro condomínio
        self._configurar_mock_supabase(mock_get_supabase, fonte_valida=True, fonte_condo="outro-condo-uuid")
        resp_outro_condo = self.client.post("/api/v1/despesas/manual", json=payload)
        self.assertEqual(resp_outro_condo.status_code, 404)
        self.assertIn("Fonte pagadora não encontrada", resp_outro_condo.json()["detail"])

    @patch("src.api.despesa_router._get_supabase")
    def test_cenario06_criacao_bem_sucedida_omitindo_fornecedor(self, mock_get_supabase):
        """Cenário 06: Criação bem-sucedida omitindo o campo fornecedor opcional (HTTP 201)."""
        self._configurar_mock_supabase(mock_get_supabase)

        # Caso A: fornecedor é None
        payload_none = self._payload_valido(fornecedor=None)
        resp_none = self.client.post("/api/v1/despesas/manual", json=payload_none)
        self.assertEqual(resp_none.status_code, 201)
        self.assertIsNone(resp_none.json()["fornecedor"])

        # Caso B: campo fornecedor ausente do dicionário JSON
        payload_sem = self._payload_valido()
        del payload_sem["fornecedor"]
        resp_sem = self.client.post("/api/v1/despesas/manual", json=payload_sem)
        self.assertEqual(resp_sem.status_code, 201)
        self.assertIsNone(resp_sem.json()["fornecedor"])

    def test_validacao_descricao_vazia_dispara_422(self):
        """Garante que descrição vazia ou composta apenas por espaços é rejeitada com 422."""
        payload_vazio = self._payload_valido(descricao="   ")
        response = self.client.post("/api/v1/despesas/manual", json=payload_vazio)
        self.assertEqual(response.status_code, 422)

    # ================================================================= #
    #  US-04: Cenários 18 a 21                                           #
    # ================================================================= #

    @patch("src.api.conciliacao_router._get_supabase")
    def test_cenario18_estorno_despesa_manual_reverte_para_validado(self, mock_get_supabase):
        """Cenário 18: Estorno de conciliação reverte o status da despesa manual para 'validado'."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        conciliacao_id = "conc-uuid-158"
        despesa_id = "desp-manual-01"

        despesas_mock = MagicMock()
        despesas_mock.select.return_value = despesas_mock
        despesas_mock.update.return_value = despesas_mock
        despesas_mock.eq.return_value = despesas_mock
        despesas_mock.in_.return_value = despesas_mock
        despesas_mock.execute.return_value = MagicMock(data=[])

        def mock_table(table_name):
            if table_name == "conciliacoes":
                q = MagicMock()
                q.select.return_value = q
                q.eq.return_value = q
                q.in_.return_value = q
                q.delete.return_value = q
                # Consulta 1: concs_tx (por transacao_id) -> vazio
                # Consulta 3: por conciliacao_id -> encontra registro
                def fake_eq(col, val):
                    if col == "transacao_id":
                        q.execute.return_value = MagicMock(data=[])
                    elif col == "id":
                        q.execute.return_value = MagicMock(data=[{
                            "id": conciliacao_id,
                            "despesa_id": despesa_id,
                            "status": "manual",
                            "transacao_id": None
                        }])
                    return q
                q.eq.side_effect = fake_eq
                return q

            elif table_name == "despesas":
                return despesas_mock

            return MagicMock()

        mock_supabase.table.side_effect = mock_table

        response = self.client.delete(f"/api/v1/conciliacao/{conciliacao_id}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        # Verifica se despesas.update foi chamado com status='validado'
        despesas_mock.update.assert_called_with({"status": "validado"})
        despesas_mock.eq.assert_called_with("id", despesa_id)

    @patch("src.api.conciliacao_router._get_supabase")
    def test_cenario19_despesa_manual_disponivel_e_busca_por_descricao(self, mock_get_supabase):
        """Cenário 19: Despesa manual com status 'validado' é retornada e filtrável por descrição."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        despesa_manual = {
            "id": "desp-manual-99",
            "condominio_id": self.condominio_id,
            "fornecedor": None,
            "numero_doc": "S/DOC",
            "data_emissao": "2026-09-30",
            "valor_total": 89.90,
            "descricao": "Tarifa Pacote de Serviços Bancários - C/C Itaú",
        }

        def mock_table(table_name):
            q = MagicMock()
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.limit.return_value = q

            if table_name == "conciliacoes":
                q.execute.return_value = MagicMock(data=[])
                return q
            elif table_name == "despesas":
                q.execute.return_value = MagicMock(data=[despesa_manual])
                return q
            return q

        mock_supabase.table.side_effect = mock_table

        # 1. Consulta geral por condomínio
        resp = self.client.get(f"/api/v1/conciliacao/despesas-disponiveis?condominio_id={self.condominio_id}")
        self.assertEqual(resp.status_code, 200)
        docs = resp.json()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["id"], "desp-manual-99")
        self.assertEqual(docs[0]["numero_doc"], "S/DOC")

        # 2. Consulta filtrando por texto da descrição ("tarifa")
        resp_q = self.client.get(f"/api/v1/conciliacao/despesas-disponiveis?condominio_id={self.condominio_id}&q=tarifa")
        self.assertEqual(resp_q.status_code, 200)
        docs_q = resp_q.json()
        self.assertEqual(len(docs_q), 1)
        self.assertEqual(docs_q[0]["id"], "desp-manual-99")

        # 3. Consulta filtrando por termo inexistente ("aluguel")
        resp_none = self.client.get(f"/api/v1/conciliacao/despesas-disponiveis?condominio_id={self.condominio_id}&q=aluguel")
        self.assertEqual(resp_none.status_code, 200)
        self.assertEqual(len(resp_none.json()), 0)

    def test_cenario20_exportacao_contabil_alterdata_partida_dobrada_integra(self):
        """Cenário 20: Exportação contábil Alterdata gera partida dobrada íntegra para despesa manual."""
        mock_db = MagicMock()

        despesa_manual_export = {
            "id": "desp-manual-1",
            "fornecedor": "Banco Itaú S.A.",
            "numero_doc": "S/DOC",
            "data_pagamento": "2026-09-30",
            "data_emissao": "2026-09-30",
            "valor_total": 89.90,
            "descricao": "Tarifa Bancaria Manutencao Conta Corrente",
            "competencia": "09/2026",
            "conta_despesa_id": "conta-debito-uuid",
            "fonte_pagadora_id": "fonte-credito-uuid",
            "plano_contas": {"codigo_contabil": "02.01.001"},
            "fontes_pagadoras": {
                "plano_conta_id": "conta-banco-uuid",
                "plano_contas": {
                    "codigo_contabil": "01.01.001",
                    "descricao": "Conta Corrente Itaú"
                }
            }
        }

        # Mock de select de despesas validadas e conciliadas
        query_val = MagicMock()
        query_val.select.return_value = query_val
        query_val.eq.return_value = query_val
        query_val.not_.is_.return_value = query_val
        query_val.execute.return_value = MagicMock(data=[despesa_manual_export])

        query_conc = MagicMock()
        query_conc.select.return_value = query_conc
        query_conc.eq.return_value = query_conc
        query_conc.not_.is_.return_value = query_conc
        query_conc.execute.return_value = MagicMock(data=[])

        call_count = 0
        def fake_table(name):
            nonlocal call_count
            if name == "despesas":
                call_count += 1
                return query_val if call_count == 1 else query_conc
            return MagicMock()

        mock_db.table.side_effect = fake_table

        service = ExportadorService(mock_db)
        conteudo_bytes = service.gerar_lote_us42(self.condominio_id, "2026-09")

        self.assertIsInstance(conteudo_bytes, bytes)
        texto = conteudo_bytes.decode("cp1252")

        # Verifica colunas da partida dobrada:
        # conta_cred (01.01.001), conta_deb (02.01.001), data (30/09/2026), cota (09/2026), valor em centavos (8990)
        self.assertIn("01.01.001", texto)
        self.assertIn("02.01.001", texto)
        self.assertIn("30/09/2026", texto)
        self.assertIn("09/2026", texto)
        self.assertIn("8990", texto)
        self.assertIn("Tarifa Bancaria Manutencao Conta Corrente", texto)

    @patch("src.api.validacao_router._get_supabase")
    def test_cenario21_consulta_despesa_manual_storage_nulo_retorna_foto_url_none(self, mock_get_supabase):
        """Cenário 21: Consulta de despesa manual sem arquivo físico retorna foto_url nula com segurança."""
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        despesa_sem_arquivo = {
            "id": "desp-manual-sem-arquivo",
            "filename": "manual_1762174800.pdf",
            "status": "validado",
            "storage_path": None,
            "bucket": None,
            "fornecedor": "Banco Itaú S.A.",
            "cnpj_cpf": None,
            "numero_doc": "S/DOC",
            "data_emissao": "2026-09-30",
            "data_vencimento": None,
            "data_pagamento": "2026-09-30",
            "valor_total": 89.90,
            "descricao": "Tarifa Bancária",
            "descricao_original": "Tarifa Bancária",
            "hash_arquivo": None,
            "sugestao_contabil": None,
            "administradora_id": self.administradora_id,
            "condominio_id": self.condominio_id,
            "chave_acesso": None,
            "competencia": "09/2026",
            "conta_despesa_id": self.conta_despesa_id,
            "fonte_pagadora_id": self.fonte_pagadora_id,
            "criado_em": "2026-11-03T15:00:00Z",
            "extraido_em": "2026-11-03T15:00:00Z",
            "erro_msg": None,
        }

        q = MagicMock()
        q.select.return_value = q
        q.eq.return_value = q
        q.single.return_value = q
        q.execute.return_value = MagicMock(data=despesa_sem_arquivo)
        mock_supabase.table.return_value = q

        response = self.client.get("/api/v1/validacao/despesas/desp-manual-sem-arquivo")
        self.assertEqual(response.status_code, 200)

        dados = response.json()
        self.assertEqual(dados["id"], "desp-manual-sem-arquivo")
        self.assertIsNone(dados["foto_url"])
        self.assertEqual(dados["status"], "validado")

        # Garante que create_signed_url NÃO foi chamado no Supabase Storage
        mock_supabase.storage.from_.assert_not_called()


if __name__ == "__main__":
    unittest.main()
