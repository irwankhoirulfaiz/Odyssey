"""
Port dari gemini-proxy.js (Node/Netlify Function) ke Python murni.

Urutan chain = urutan fallback: kalau model paling depan (atau preferred_model
dari dropdown) kena error yang "boleh di-retry" (rate limit, model
retired/gak available, dst - lihat is_retryable_model_error di bawah),
otomatis nyoba model berikutnya di daftar ini sampai ada yang jawab.

Mapping nama tampilan "Odyssey x.x" -> id Gemini asli disimpan di sisi
frontend (report-agent.html, konstanta ODYSSEY_MODEL_NAMES), urutannya
sengaja disamain persis biar gak bingung pas debug.

CATATAN: "gemini-2.5-flash-lite" & "gemini-2.5-flash" SENGAJA dikeluarin
dari chain ini. Google udah nutup akses seri 2.5 buat API key baru
("This model ... is no longer available to new users" -> 404), jadi 2
model itu gak akan pernah kepakai sama key yang baru di-generate. Kalau
suatu saat ternyata key-nya masih dapet akses (key lama/legacy), tinggal
tambahin lagi ke list ini.
"""

import json
import re
import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

GEMINI_MODEL_CHAIN: list[str] = [
    "gemini-3-flash",         # Odyssey 3.0
    "gemini-3.1-flash-lite",  # Odyssey 3.1
    "gemini-3.5-flash",       # Odyssey 3.5 Pro
    "gemini-3.5-flash-lite",  # Odyssey 3.5
    "gemini-3.6-flash",       # Odyssey 3.6
    "gemini-3.7-flash",       # Odyssey 3.7
    "gemini-3.8-flash",       # Odyssey 3.8
]

# Tangga thinkingLevel dari paling hemat ke paling "mikir". Dukungan level
# ini BEDA-BEDA tiap model & sering berubah tiap Google rilis versi baru
# (contoh nyata: "minimal" jalan di Gemini 3.7 Flash tapi udah gak
# didukung lagi di Gemini 3.8 Flash). Daripada hardcode 1 level yang
# gampang basi, kalau ketemu error "thinking level X not supported",
# proxy naikin level ini setapak demi setapak di MODEL YANG SAMA dulu
# sebelum nyerah & pindah ke model berikutnya di chain.
THINKING_LEVEL_LADDER: list[str] = ["minimal", "low", "medium", "high"]

# Prompt yang GEDE sengaja GAK di-retry sebagai 1 putaran ekstra kalau semua
# model kena rate limit — ngirim ulang payload segede itu ke 7 model cuma
# bikin kuota token per-menit makin cepet abis, bukan bantu. Cuma prompt
# kecil (obrolan ringan) yang worth it dicoba 1x putaran tambahan.
SMALL_PROMPT_CHAR_LIMIT = 20000  # ~5rb token, kasar

_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"([\d.]+)s"', re.IGNORECASE)


def gemini_url_for(model: str) -> str:
    return (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + model
        + ":generateContent"
    )


def err_msg_of(data: Optional[dict]) -> str:
    if not data:
        return ""
    return json.dumps(data.get("error", ""))


def retry_delay_seconds_of(data: Optional[dict]) -> float:
    """Gemini kadang ngasih tau di body error berapa detik lagi kudu
    nunggu (field "retryDelay", format "12.3s"). Kalau ada, pakai itu;
    kalau nggak, fallback ke jeda pendek. Di-cap 1-6 detik biar gak
    nunggu kelamaan."""
    msg = err_msg_of(data)
    m = _RETRY_DELAY_RE.search(msg)
    seconds = float(m.group(1)) if m else 2.0
    return min(max(seconds, 1.0), 6.0)


def is_rate_limit_error(status: int, data: Optional[dict]) -> bool:
    """Kena limit pemakaian (kuota/rate limit) - model-nya sendiri sehat,
    cuma lagi penuh. Layak dicoba ulang, baik di model yang sama (nanti)
    maupun pindah ke model lain."""
    if status == 429:
        return True
    return bool(re.search(r"RESOURCE_EXHAUSTED", err_msg_of(data), re.IGNORECASE))


def is_overloaded_error(status: int, data: Optional[dict]) -> bool:
    """Model-nya lagi kebanjiran trafik di sisi Google (503 "overloaded"/
    "experiencing high demand"/UNAVAILABLE) - BUKAN soal kuota kita, tapi
    tetep layak pindah ke model lain di chain."""
    if status == 503:
        return True
    msg = err_msg_of(data)
    return bool(
        re.search(r"UNAVAILABLE", msg, re.IGNORECASE)
        or re.search(r"overloaded", msg, re.IGNORECASE)
        or re.search(r"experiencing high demand", msg, re.IGNORECASE)
    )


def is_model_unavailable_error(status: int, data: Optional[dict]) -> bool:
    """Model-nya sendiri yang bermasalah: udah di-retire/gak available
    buat key ini (404), atau ID model salah/gak ketemu. Gak ada gunanya
    diulang di model yang sama - harus lompat ke model LAIN di chain."""
    if status == 404:
        return True
    msg = err_msg_of(data)
    return bool(
        re.search(r"NOT_FOUND", msg, re.IGNORECASE)
        or re.search(r"no longer available", msg, re.IGNORECASE)
    )


def is_thinking_level_error(status: int, data: Optional[dict]) -> bool:
    """Model-nya nolak nilai thinkingLevel yang dikirim (400). Ini
    spesifik ke parameter, bukan ke model-nya - jadi masih layak dicoba
    ulang di MODEL YANG SAMA pakai level lain di THINKING_LEVEL_LADDER,
    sebelum nyerah & pindah model."""
    if status != 400:
        return False
    msg = err_msg_of(data)
    return bool(re.search(r"thinking", msg, re.IGNORECASE)) and bool(
        re.search(r"not supported", msg, re.IGNORECASE)
    )


def build_chain(preferred_model: Optional[str]) -> list[str]:
    if not preferred_model or preferred_model not in GEMINI_MODEL_CHAIN:
        return list(GEMINI_MODEL_CHAIN)
    return [preferred_model] + [m for m in GEMINI_MODEL_CHAIN if m != preferred_model]


@dataclass
class GeminiResult:
    status: int
    data: dict


@dataclass
class ChainPassResult:
    done: bool
    status_code: Optional[int] = None
    body: Optional[dict] = None
    last_result: Optional[GeminiResult] = None


async def call_gemini(
    client: httpx.AsyncClient,
    model: str,
    body_base: dict,
    thinking_level: str,
    api_key: str,
) -> GeminiResult:
    body = dict(body_base)
    generation_config = dict(body_base.get("generationConfig", {}))
    generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    body["generationConfig"] = generation_config

    resp = await client.post(
        gemini_url_for(model),
        params={"key": api_key},
        json=body,
        timeout=30.0,
    )
    try:
        data = resp.json()
    except ValueError:
        data = {"error": {"message": resp.text}}
    return GeminiResult(status=resp.status_code, data=data)


async def run_chain_pass(
    client: httpx.AsyncClient,
    model_chain: list[str],
    body_base: dict,
    start_ladder_idx: int,
    api_key: str,
) -> ChainPassResult:
    """Jalanin 1x "putaran" nyisir seluruh model_chain. Kalau ada yang
    sukses (atau error yang gak layak di-retry), balikin langsung sebagai
    respons final (done=True). Kalau SEMUA model di putaran ini abis
    dicoba & semuanya rate-limit/gak-available, balikin done=False biar
    caller bisa mutusin mau retry putaran lagi atau nyerah."""
    last_result: Optional[GeminiResult] = None

    for model in model_chain:
        # Buat MODEL INI, mulai dari level yang diminta terus naik tangga
        # (minimal -> low -> medium -> high) kalau kena error "thinking
        # level not supported". Begitu level-nya cocok atau errornya
        # BUKAN soal thinking level, langsung berhenti di sini (baik
        # sukses maupun error lain yang mesti pindah model).
        for lvl in range(start_ladder_idx, len(THINKING_LEVEL_LADDER)):
            thinking_level = THINKING_LEVEL_LADDER[lvl]
            try:
                result = await call_gemini(client, model, body_base, thinking_level, api_key)
                last_result = result

                if is_thinking_level_error(result.status, result.data):
                    continue  # naik ke level berikutnya, model yang sama

                if (
                    is_rate_limit_error(result.status, result.data)
                    or is_model_unavailable_error(result.status, result.data)
                    or is_overloaded_error(result.status, result.data)
                ):
                    break  # nyerah di model ini, lanjut ke model berikutnya di chain

                # Sukses ATAU error lain yang gak layak di-retry (mis.
                # safety block, payload salah) -> langsung balikin ke
                # client apa adanya.
                result.data["modelUsed"] = model
                return ChainPassResult(done=True, status_code=result.status, body=result.data)

            except httpx.HTTPError as e:
                last_result = GeminiResult(
                    status=502,
                    data={"error": f"Gagal menghubungi Gemini API ({model}): {e}"},
                )
                break  # error jaringan, gak ada gunanya ganti-ganti thinkingLevel

    return ChainPassResult(done=False, last_result=last_result)


async def run_gemini_chat(
    *,
    system: Optional[str],
    contents: list[dict],
    max_tokens: Optional[int],
    thinking_level: Optional[str],
    preferred_model: Optional[str],
    api_key: str,
) -> tuple[int, dict]:
    """Entry point utama - dipanggil dari endpoint FastAPI. Balikin
    (status_code, body_dict) siap dikirim sebagai JSON response."""

    requested_level = thinking_level if thinking_level in THINKING_LEVEL_LADDER else "minimal"
    start_idx = THINKING_LEVEL_LADDER.index(requested_level)

    body_base: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": max_tokens or 1000,
            # Maksa Gemini balikin JSON yang beneran valid (bukan cuma
            # nurut instruksi teks di system prompt yang sifatnya
            # "permintaan" doang).
            "responseMimeType": "application/json",
        },
    }
    if system:
        body_base["system_instruction"] = {"parts": [{"text": system}]}

    model_chain = build_chain(preferred_model)
    prompt_char_len = len(json.dumps(body_base))

    async with httpx.AsyncClient() as client:
        pass_result = await run_chain_pass(client, model_chain, body_base, start_idx, api_key)

        if (
            not pass_result.done
            and pass_result.last_result
            and is_rate_limit_error(pass_result.last_result.status, pass_result.last_result.data)
            and prompt_char_len < SMALL_PROMPT_CHAR_LIMIT
        ):
            await asyncio.sleep(retry_delay_seconds_of(pass_result.last_result.data))
            pass_result = await run_chain_pass(client, model_chain, body_base, start_idx, api_key)

    if pass_result.done:
        return pass_result.status_code or 200, pass_result.body or {}

    last_result = pass_result.last_result
    if last_result:
        return last_result.status, last_result.data
    return 502, {"error": "Semua model di GEMINI_MODEL_CHAIN gagal, gak ada respons."}
