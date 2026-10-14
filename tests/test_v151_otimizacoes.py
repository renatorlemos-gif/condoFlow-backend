import os
import io
import asyncio
import unittest
from unittest.mock import patch
from fastapi import UploadFile
from fastapi.testclient import TestClient
from fastapi.middleware.gzip import GZipMiddleware
from google.genai.errors import APIError
import pymupdf

from src.api.main import app
from src.utils.despesa_parser import DespesaParser


class TestV151OtimizacoesBackend(unittest.TestCase):
    def test_gzip_middleware_presence(self):
        """Verifica se GZipMiddleware está registrado na pilha de middlewares."""
        has_gzip = any(
            middleware.cls == GZipMiddleware
            for middleware in app.user_middleware
        )
        self.assertTrue(has_gzip, "GZipMiddleware deve estar presente na aplicação FastAPI.")

    def test_gzip_compression_for_large_payload(self):
        """US-05 Cenário 01: Payload > 1000 bytes deve receber Content-Encoding: gzip quando solicitado."""
        client = TestClient(app)
        # /openapi.json é tipicamente > 1000 bytes
        res = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-encoding"), "gzip")

    def test_pymupdf_compression_options(self):
        """US-05 Cenário 03 e 04: Valida integridade e compactação de stream com deflate=True e garbage=4."""
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), "CondoFlow v1.51 - Teste de Compressao de Stream")
        
        # Gera binário com compressão
        compressed_bytes = doc.write(deflate=True, garbage=4)
        self.assertGreater(len(compressed_bytes), 0)
        
        # Verifica integridade de abertura sem corrupção
        opened_doc = pymupdf.open("pdf", compressed_bytes)
        self.assertEqual(opened_doc.page_count, 1)
        text = opened_doc[0].get_text()
        self.assertIn("CondoFlow v1.51 - Teste de Compressao de Stream", text)

    def test_gemini_models_defaults_and_failover_on_503(self):
        """Valida se os modelos padrão são 3.5-flash-lite e flash-lite-latest, e se o failover chaveia para os fallbacks no erro 503."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-api-key"}, clear=False):
            os.environ.pop("GEMINI_MODEL_PRIMARY", None)
            os.environ.pop("GEMINI_MODEL_FALLBACK", None)

            parser = DespesaParser()
            models_called = []

            class MockResponse:
                text = '{"cnpj_cpf_fornecedor": "12.345.678/0001-90", "nome_fornecedor": "Teste Ltda", "numero_despesa": "123", "data_emissao": "2026-10-10", "data_pagamento": "2026-10-11", "valor_total_bruto": "150,00", "descricao": "Teste Ltda Danfe 123", "contexto_sintetizado": "Servicos", "competencia": "10/2026"}'

            def fake_generate_content(*args, **kwargs):
                model = kwargs.get("model")
                models_called.append(model)
                if len(models_called) == 1:
                    raise APIError(503, {"error": {"code": 503, "message": "503 UNAVAILABLE"}})
                elif len(models_called) == 2:
                    raise APIError(503, {"error": {"code": 503, "message": "503 UNAVAILABLE"}})
                return MockResponse()

            parser.client.models.generate_content = fake_generate_content

            fake_file = UploadFile(
                filename="teste.pdf",
                file=io.BytesIO(b"%PDF-1.4 fake content"),
                headers={"content-type": "application/pdf"}
            )

            dados, h = asyncio.run(parser.parse_despesa(fake_file))

            self.assertEqual(models_called[0], "gemini-3.5-flash-lite")
            self.assertEqual(models_called[1], "gemini-flash-lite-latest")
            self.assertEqual(models_called[2], "gemini-3-flash-preview")
            self.assertEqual(dados.valor_total, 150.0)


if __name__ == "__main__":
    unittest.main()
