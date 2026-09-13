# Entry point khusus Vercel. Vercel nge-detect variabel "app" di file ini
# dan otomatis nganggepnya sebagai ASGI app (FastAPI). Logic sebenarnya
# tetap di main.py (satu file yang sama juga bisa dipakai buat jalanin
# lokal via "uvicorn main:app").
from main import app  # noqa: F401
