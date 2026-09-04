import asyncio
import logging
import os

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from src.api.documento_router import router as documento_router

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
# ------------------------------------------------------------------ #
@app.post("/api/processar-extrato")
async def processar_extrato(
    file: UploadFile = File(...),
    banco: str = Form(...),
):
    conteudo_bytes   = await file.read()
    nome_original    = file.filename or "extrato.xlsx"
    banco_normalizado = banco.strip().lower()

    try:
        if banco_normalizado == "bradesco":
            from src.utils.bradesco_parser import processar_extrato_bradesco_bytes
            excel_io, nome_saida = processar_extrato_bradesco_bytes(conteudo_bytes, nome_original)
        elif banco_normalizado == "santander":
            from src.utils.santander_parser import processar_extrato_santander_bytes
            excel_io, nome_saida = processar_extrato_santander_bytes(conteudo_bytes, nome_original)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Banco inválido ou não suportado: '{banco}'. Utilize 'bradesco' ou 'santander'."
            )
    except ImportError as ie:
        raise HTTPException(status_code=500, detail=f"Erro de importação do parser: {str(ie)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar o extrato: {str(e)}")

    return StreamingResponse(
        excel_io,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_saida}"},
    )
