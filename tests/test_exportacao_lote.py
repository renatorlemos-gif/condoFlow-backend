import unittest
from unittest.mock import MagicMock, patch
from src.api.exportacao_router import _formatar_competencia, _slugify, exportar_lote_us42


class TestExportacaoLoteNomeArquivo(unittest.IsolatedAsyncioTestCase):
    def test_formatar_competencia(self):
        """Valida a conversão de competência para o padrão MM-AAAA."""
        # YYYY-MM
        self.assertEqual(_formatar_competencia("2026-10"), "10-2026")
        self.assertEqual(_formatar_competencia("2026-08"), "08-2026")
        # MM/YYYY
        self.assertEqual(_formatar_competencia("10/2026"), "10-2026")
        self.assertEqual(_formatar_competencia("08/2026"), "08-2026")
        # MM-YYYY (já no formato)
        self.assertEqual(_formatar_competencia("10-2026"), "10-2026")
        # YYYY/MM
        self.assertEqual(_formatar_competencia("2026/10"), "10-2026")

    def test_slugify(self):
        """Valida a geração de slugs seguros para administradora e condomínio."""
        self.assertEqual(_slugify("Alpha Administradora"), "alpha-administradora")
        self.assertEqual(_slugify("Condomínio Edifício Solar das Flores"), "condominio-edificio-solar-das-flores")
        self.assertEqual(_slugify("ADM & GESTÃO S/A"), "adm-gestao-s-a")

    @patch("src.api.exportacao_router._get_supabase")
    @patch("src.services.exportador_service.ExportadorService.gerar_lote_us42")
    async def test_exportar_lote_us42_filename_header(self, mock_gerar_lote, mock_get_supabase):
        """Valida se o endpoint GET /api/v1/exportacao/lote-us42 monta o Content-Disposition com o nome padronizado."""
        mock_gerar_lote.return_value = b"CONTEUDO_LOTE_TESTE"

        # Mock Supabase
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        # Mock query condominios
        mock_condo_query = MagicMock()
        mock_condo_resp = MagicMock()
        mock_condo_resp.data = [{"nome": "Condomínio Residencial Parque", "administradora_id": "adm-uuid-123"}]
        mock_condo_query.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_condo_resp

        # Mock query administradoras
        mock_adm_query = MagicMock()
        mock_adm_resp = MagicMock()
        mock_adm_resp.data = [{"nome": "Habita Administradora"}]
        mock_adm_query.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_adm_resp

        def table_side_effect(table_name):
            if table_name == "condominios":
                return mock_condo_query
            elif table_name == "administradoras":
                return mock_adm_query
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        response = await exportar_lote_us42(
            condominio_id="condo-uuid-456",
            competencia="2026-10"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "text/plain")
        expected_disposition = 'attachment; filename="habita-administradora_condominio-residencial-parque_10-2026.txt"'
        self.assertEqual(response.headers.get("Content-Disposition"), expected_disposition)

    def test_gerar_lote_us42_bloqueia_quando_partida_dobrada_incompleta(self):
        """Valida que gerar_lote_us42 lança HTTPException 400 se nenhum lançamento possuir partida dobrada completa."""
        from fastapi import HTTPException
        from src.services.exportador_service import ExportadorService

        mock_supabase = MagicMock()
        service = ExportadorService(mock_supabase)
        
        # Simula obter_preview_us42 retornando lançamentos sem conta_cred (ex: fonte sem plano_conta_id)
        service.obter_preview_us42 = MagicMock(return_value=[
            {
                "id": "doc-1",
                "fornecedor": "Fornecedor Teste",
                "data_pagamento": "2026-09-01",
                "valor_total": 100.0,
                "conta_deb": "197",
                "conta_cred": "", # Faltando conta credora!
                "competencia": "09/2026"
            }
        ])

        with self.assertRaises(HTTPException) as ctx:
            service.gerar_lote_us42("condo-123", "2026-09")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Não há lançamentos aptos para exportação", ctx.exception.detail)

    def test_gerar_lote_us42_sucesso_quando_partida_dobrada_completa(self):
        """Valida a geração correta do lote em cp1252 quando as contas de débito e crédito estão configuradas."""
        from src.services.exportador_service import ExportadorService

        mock_supabase = MagicMock()
        service = ExportadorService(mock_supabase)
        
        service.obter_preview_us42 = MagicMock(return_value=[
            {
                "id": "doc-1",
                "fornecedor": "Ifood Benefícios",
                "data_pagamento": "2026-09-01",
                "valor_total": 1750.0,
                "descricao": "Ticket alimentação",
                "conta_deb": "197",
                "conta_cred": "019",
                "competencia": "09/2026"
            }
        ])

        bytes_lote = service.gerar_lote_us42("condo-123", "2026-09")
        texto = bytes_lote.decode("cp1252")
        self.assertIn("019,197,01/09/2026,09/2026", texto)
        self.assertIn("175000", texto)


if __name__ == "__main__":
    unittest.main()
