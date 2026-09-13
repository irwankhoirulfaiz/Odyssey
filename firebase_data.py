"""
Baca data dari Firebase Realtime Database yang sama dipakai module-module
lain (inbound.html, outbound.html, inventory-control.html, rest-time.html,
performance-bagger.html).

Backend Python akses langsung pakai Admin SDK - ini BEDA dari client SDK
yang dipakai frontend (Admin SDK punya akses penuh, bypass Realtime
Database Rules, jadi validasi akses user harus tetap dilakuin di endpoint
FastAPI lewat verify_firebase_token, bukan diserahin ke Rules).

Sesuaikan nama node di bawah ini kalau berbeda dari yang sebenernya ada
di project Firebase lo.
"""

from firebase_admin import db

# Node-node yang sekarang dibaca report-agent.html langsung dari client -
# dipindah ke sini biar backend Python bisa narik data yang sama.
NODE_INBOUND_TRACKING = "prDcInboundTracking"
NODE_REST_ASSET_MONITORING = "prDcMonitoring"
NODE_ODYSSEY_AGENT = "odysseyAgent"


def get_inbound_tracking() -> dict:
    ref = db.reference(NODE_INBOUND_TRACKING)
    return ref.get() or {}


def get_rest_asset_monitoring() -> dict:
    ref = db.reference(NODE_REST_ASSET_MONITORING)
    return ref.get() or {}


def get_chat_history(uid: str) -> list:
    ref = db.reference(f"{NODE_ODYSSEY_AGENT}/{uid}/chatHistory")
    data = ref.get()
    return data or []


def get_memory_facts(uid: str) -> list:
    ref = db.reference(f"{NODE_ODYSSEY_AGENT}/{uid}/memoryFacts")
    data = ref.get()
    return data or []


def save_chat_history(uid: str, history: list) -> None:
    ref = db.reference(f"{NODE_ODYSSEY_AGENT}/{uid}/chatHistory")
    ref.set(history)


def save_memory_facts(uid: str, facts: list) -> None:
    ref = db.reference(f"{NODE_ODYSSEY_AGENT}/{uid}/memoryFacts")
    ref.set(facts)
