import sys
import os

# Adiciona o diretório raiz do backend ao sys.path para execução de testes
backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)
