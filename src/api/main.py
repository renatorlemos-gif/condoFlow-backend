from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from src.utils.bradesco_parser import processar_extrato_bradesco_bytes

app = FastAPI(title="CondoFlow API", version="1.0")

# Configuração de CORS atualizada
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://condo-flow-frontend.vercel.app",  # Seu domínio principal atual
        "https://condo-flow-three.vercel.app",
        "https://condo-flow-frontend-45obqgotq-rl-desk.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

@app.post("/api/processar-extrato-bradesco")
async def processar_extrato(file: UploadFile = File(...)):
    conteudo_bytes = await file.read()
    excel_io = processar_extrato_bradesco_bytes(conteudo_bytes)
    
    return StreamingResponse(
        excel_io,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=extrato_consolidado_bradesco.xlsx"}
    )