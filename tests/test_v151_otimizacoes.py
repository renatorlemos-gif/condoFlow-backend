import unittest
from fastapi.testclient import TestClient
from fastapi.middleware.gzip import GZipMiddleware
import pymupdf

from src.api.main import app


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


if __name__ == "__main__":
    unittest.main()
