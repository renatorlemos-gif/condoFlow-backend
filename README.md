# CondoFlow Backend

## Ambiente Local (Docker)

Para iniciar o ambiente localmente com o Docker, execute o comando abaixo na raiz do projeto onde se encontra o `docker-compose.yml`:

```bash
docker-compose up -d --build
```

**Nota sobre atualizações de código:** 
O `Dockerfile` do backend não utiliza o modo `--reload` do Uvicorn/FastAPI. Portanto, sempre que você realizar alterações no código-fonte, será necessário reiniciar o container do backend para que as mudanças sejam aplicadas. Para isso, execute:

```bash
docker-compose restart backend
```
