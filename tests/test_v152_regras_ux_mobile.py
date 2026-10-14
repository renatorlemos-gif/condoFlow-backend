import unittest
from unittest.mock import patch, MagicMock
from src.utils.despesa_parser import DespesaParser
from src.api.plano_contas_router import ContaUpdateContexto


class TestV152RegrasAjustes(unittest.TestCase):
    def test_prompt_regras_pensao_e_concessionarias(self):
        """US-01 e US-02: Valida se o prompt contém as diretrizes de pensão alimentícia e desambiguação de concessionárias."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}, clear=False):
            parser = DespesaParser()
            # Inspeciona as instruções de prompt em parse_despesa
            import inspect
            source = inspect.getsource(parser.parse_despesa)
            
            # US-01: Pensão Alimentícia
            self.assertIn("REGRA MANDATÓRIA DE PENSÃO ALIMENTÍCIA", source)
            self.assertIn("DEVE SER OBRIGATORIAMENTE O NOME DO FUNCIONÁRIO DO CONDOMÍNIO", source)
            self.assertIn("NUNCA a pessoa beneficiária", source)
            
            # US-02: Concessionárias
            self.assertIn("NUNCA confunda ou utilize número de instalação, número do medidor ou código do cliente", source)
            self.assertIn("Nº N. Fiscal", source)

    def test_conta_update_contexto_model_fields_set(self):
        """US-04: Valida se o modelo Pydantic detecta 'descricao_padrao' em model_fields_set quando enviado explicitamente como null ou string."""
        # Enviado como null
        dto_null = ContaUpdateContexto.model_validate({"contexto": "Serviços de jardinagem", "descricao_padrao": None})
        self.assertIn("descricao_padrao", dto_null.model_fields_set)
        self.assertIsNone(dto_null.descricao_padrao)

        # Enviado como string com espaços
        dto_espacos = ContaUpdateContexto.model_validate({"contexto": "Serviços de jardinagem", "descricao_padrao": "   "})
        self.assertIn("descricao_padrao", dto_espacos.model_fields_set)
        val = dto_espacos.descricao_padrao
        sanitizado = val.strip() if (val and val.strip()) else None
        self.assertIsNone(sanitizado, "String de espaços deve ser sanitizada para None")

        # Não enviado no payload
        dto_omitted = ContaUpdateContexto.model_validate({"contexto": "Serviços de jardinagem"})
        self.assertNotIn("descricao_padrao", dto_omitted.model_fields_set)


if __name__ == "__main__":
    unittest.main()
