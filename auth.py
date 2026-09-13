"""
Verifikasi Firebase ID Token yang dikirim frontend lewat header
Authorization: Bearer <token>.

Ini gantiin peran auth-guard.js buat sisi backend - frontend tetap login
pakai Firebase Auth SDK seperti biasa, cuma sekarang tokennya perlu
disertain tiap manggil backend Python.
"""

import os

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from fastapi import Header, HTTPException

_firebase_app: firebase_admin.App | None = None


def init_firebase() -> None:
    """Panggil sekali pas startup. Kredensial diambil dari environment
    variable FIREBASE_SERVICE_ACCOUNT_KEY (isinya JSON service account
    lengkap, bukan firebaseConfig yang biasa dipakai di sisi client)."""
    global _firebase_app
    if _firebase_app is not None:
        return

    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY")
    if not service_account_json:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_KEY belum di-set di Environment Variables"
        )

    import json

    cred = credentials.Certificate(json.loads(service_account_json))
    _firebase_app = firebase_admin.initialize_app(cred)


async def verify_firebase_token(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency - taruh di parameter endpoint yang butuh login.
    Balikin decoded token (isinya uid, email, dst) kalau valid, atau
    langsung raise HTTPException 401 kalau nggak.

    init_firebase() dipanggil di sini (bukan cuma di event "startup") biar
    tetap aman jalan di lingkungan serverless (Vercel) yang gak selalu
    nge-trigger event startup ASGI di tiap cold start."""
    init_firebase()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Header Authorization: Bearer <token> wajib ada")

    id_token = authorization.removeprefix("Bearer ").strip()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token gak valid: {e}")

    return decoded


# ACCESS_MAP sederhana - lo bisa perluas ini biar mirror ACCESS_MAP di
# auth-guard.js kalau butuh pembatasan akses per-email/per-modul.
def require_access(decoded_token: dict) -> None:
    email = decoded_token.get("email", "")
    if not email:
        raise HTTPException(status_code=403, detail="Akun tanpa email gak diizinkan")
    # TODO: samain logic-nya dengan ACCESS_MAP di auth-guard.js kalau
    # Odyssey perlu whitelist email tertentu.
