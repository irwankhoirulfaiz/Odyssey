"""
Backend Python buat Odyssey (Report-Agent) versi independen.

Gantiin gemini-proxy.js sepenuhnya - frontend (report-agent.html) manggil
API ini langsung, bukan lagi ke Netlify Function.

Jalanin lokal:
    uvicorn main:app --reload --port 8000

Deploy ke Vercel:
    File api/index.py re-export "app" dari sini, vercel.json nge-rewrite
    semua path ke situ. Vercel otomatis detect & jalanin sebagai ASGI app,
    gak perlu start command manual.

Deploy ke Render (alternatif kalau balik pakai Render):
    Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import init_firebase, require_access, verify_firebase_token
from gemini_chain import run_gemini_chat
from firebase_data import get_inbound_tracking, get_rest_asset_monitoring

app = FastAPI(title="Odyssey Backend")

# Ganti "*" dengan domain frontend Odyssey yang sebenarnya sebelum production
# (misal https://odyssey.namadomainlo.com), jangan biarin "*" kalau endpoint
# udah nyimpen/baca data sensitif.
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_firebase()


class ChatRequest(BaseModel):
    system: str | None = None
    contents: list[dict]
    max_tokens: int | None = None
    thinking_level: str | None = None
    preferred_model: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(payload: ChatRequest, decoded_token: dict = Depends(verify_firebase_token)):
    require_access(decoded_token)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY belum di-set")

    status_code, body = await run_gemini_chat(
        system=payload.system,
        contents=payload.contents,
        max_tokens=payload.max_tokens,
        thinking_level=payload.thinking_level,
        preferred_model=payload.preferred_model,
        api_key=api_key,
    )
    # Sengaja balikin body APA ADANYA (bukan lewat "raise HTTPException", yang
    # bakal dibungkus FastAPI jadi {"detail": ...}) - frontend (report-agent.html)
    # ngarepin bentuk {"error": {...}} persis kayak balasan asli Gemini API,
    # baik pas sukses maupun gagal.
    return JSONResponse(status_code=status_code, content=body)


@app.get("/api/data/inbound")
def data_inbound(decoded_token: dict = Depends(verify_firebase_token)):
    require_access(decoded_token)
    return get_inbound_tracking()


@app.get("/api/data/rest-asset")
def data_rest_asset(decoded_token: dict = Depends(verify_firebase_token)):
    require_access(decoded_token)
    return get_rest_asset_monitoring()
