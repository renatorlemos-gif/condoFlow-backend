from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import io

from src.api.documento_router import router as documento_router

app = FastAPI(title="CondoFlow API", version="1.0")

# Configuração de CORS com regex para previews dinâmicos da Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://condo-flow-frontend.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000"
    ],
    allow_origin_regex=r"https://condo-flow-frontend-.*\.vercel\.app|https://condo-flow-.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Inclusão dos novos endpoints para escaneamento e gestão de lote contábil
app.include_router(documento_router)

@app.post("/api/processar-extrato")
async def processar_extrato(
    file: UploadFile = File(...),
    banco: str = Form(...)  # O front-end enviará 'bradesco' ou 'santander'
):
    conteudo_bytes = await file.read()
    nome_original = file.filename or "extrato.xlsx"
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
        raise HTTPException(
            status_code=500, 
            detail=f"Erro de importação do parser para o banco {banco}: {str(ie)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Erro ao processar o extrato: {str(e)}"
        )

    return StreamingResponse(
        excel_io,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_saida}"}
    )