import asyncio
import logging
import os

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from src.api.documento_router import router as documento_router
from src.api.validacao_router import router as validacao_router
from src.api.conciliacao_router import router as conciliacao_router
from src.api.contexto_router import router as contexto_router
from src.api.plano_contas_router import router as plano_contas_router
from src.api.balancete_router import router as balancete_router
from src.api.classificacao_router import router as classificacao_router
from src.api.exportacao_router import router as exportacao_router
from src.api.cadastros_router import router as cadastros_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="CondoFlow API", version="1.0")

# ------------------------------------------------------------------ #
#  CORS                                                               #
# ------------------------------------------------------------------ #
_cors_origins_env = os.getenv("CORS_ORIGINS")
if _cors_origins_env:
    allow_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
else:
    allow_origins = [
        "https://condo-flow-frontend.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
    ]

allow_origin_regex = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"https://condo-flow-frontend-.*\.vercel\.app|https://condo-flow-.*\.vercel\.app",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# ------------------------------------------------------------------ #
#  Routers                                                            #
# ------------------------------------------------------------------ #
app.include_router(documento_router)
app.include_router(validacao_router)
app.include_router(conciliacao_router)
app.include_router(contexto_router)
app.include_router(plano_contas_router)
app.include_router(balancete_router)
app.include_router(classificacao_router)
app.include_router(exportacao_router)
app.include_router(cadastros_router)


# ------------------------------------------------------------------ #
#  Worker de extração em segundo plano                                #
# ------------------------------------------------------------------ #
@app.on_event("startup")
async def startup_event():
    from src.workers.extrator_worker import rodar_worker
    asyncio.create_task(rodar_worker())
    logger.info("Worker de extração iniciado em background.")


# ------------------------------------------------------------------ #
#  Processar Extrato Bancário                                         #
#  Persiste no banco com isolamento por Administradora e Condomínio   #
# ------------------------------------------------------------------ #
@app.post("/api/processar-extrato")
async def processar_extrato(
    file: UploadFile = File(...),
    banco: str = Form(...),
    administradora_id: str = Form("adm-alpha"),
    condominio_id: str = Form("condo-alpha-01"),
    condo_nome: str = Form(None),
    conta_bancaria_id: str = Form(None),
):
    conteudo_bytes = await file.read()
    nome_original  = file.filename or "extrato.xlsx"
    condo_nome_final = condo_nome or os.environ.get("CONDO_NOME", "Condominio")

    try:
        from src.services.extrato_service import processar_e_persistir
        excel_io, nome_saida, qtd_transacoes = await processar_e_persistir(
            conteudo_bytes=conteudo_bytes,
            nome_arquivo=nome_original,
            banco=banco,
            condo_nome=condo_nome_final,
            administradora_id=administradora_id,
            condominio_id=condominio_id,
            conta_bancaria_id=conta_bancaria_id,
        )
        logger.info(f"Extrato processado: {qtd_transacoes} transações salvas no banco (Condomínio: {condominio_id}).")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar o extrato: {str(e)}")

    return StreamingResponse(
        excel_io,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_saida}"},
    )
