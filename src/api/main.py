from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import io

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

@app.post("/api/processar-extrato-bradesco")
async def processar_extrato(file: UploadFile = File(...)):
    conteudo_bytes = await file.read()
    
    # Importação interna para evitar quebra caso o módulo demore a carregar
    try:
        from src.utils.bradesco_parser import processar_extrato_bradesco_bytes
        excel_io = processar_extrato_bradesco_bytes(conteudo_bytes)
    except ImportError:
        # Fallback temporário caso o caminho do utils seja diferente no seu repositório
        excel_io = io.BytesIO(conteudo_bytes)

    return StreamingResponse(
        excel_io,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=extrato_consolidado_bradesco.xlsx"}
    )