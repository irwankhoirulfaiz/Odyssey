# Odyssey Backend (Python)

Backend independen buat Odyssey/Report-Agent - gantiin `gemini-proxy.js`
sepenuhnya. Ditulis pakai FastAPI, dideploy di **Vercel** (serverless
function Python, gratis tanpa kartu kredit).

## Struktur

- `main.py` — entry point FastAPI, endpoint `/api/chat`, `/api/data/*`
- `api/index.py` — entry point khusus Vercel, re-export `app` dari
  `main.py` (Vercel deteksi variabel `app` di file ini sebagai ASGI app)
- `vercel.json` — rewrite semua path request ke `api/index.py`, biar
  routing internal FastAPI (`/health`, `/api/chat`, dst) tetap jalan
- `gemini_chain.py` — port 1:1 dari `gemini-proxy.js` (model fallback
  chain, thinking level ladder, deteksi error, retry)
- `auth.py` — verifikasi Firebase ID Token dari frontend (init Firebase
  dipanggil lazy di tiap request, bukan cuma di event startup, biar aman
  di lingkungan serverless)
- `firebase_data.py` — baca data module lain (inbound, rest-time, dst)
  dari Realtime Database yang sama
- `render.yaml` — buat opsi deploy alternatif ke Render (lihat bagian
  paling bawah), gak dipakai kalau deploy ke Vercel

## Jalanin lokal

```bash
pip install -r requirements.txt
cp .env.example .env   # isi GEMINI_API_KEY & FIREBASE_SERVICE_ACCOUNT_KEY
uvicorn main:app --reload --port 8000
```

Karena `firebase-admin` baca env var langsung (bukan lewat python-dotenv
otomatis), pastikan variabel di `.env` sudah di-export ke shell, atau
tambahkan `load_dotenv()` manual di awal `main.py` kalau mau otomatis pas
development.

## Deploy ke Vercel

**Lewat dashboard (paling gampang):**
1. Push folder ini ke repo Git (GitHub/GitLab/Bitbucket)
2. Buka [vercel.com](https://vercel.com) > New Project > import repo ini
3. Framework Preset biarin "Other" (Vercel otomatis detect Python lewat
   `vercel.json` + folder `api/`)
4. Sebelum klik Deploy, buka bagian **Environment Variables**, isi:
   - `GEMINI_API_KEY`
   - `FIREBASE_SERVICE_ACCOUNT_KEY` (isi JSON service account lengkap,
     Vercel support paste multi-baris langsung ke kolom value)
   - `ALLOWED_ORIGINS` (domain frontend Odyssey, misal
     `https://dashboardpalangkarayadc.netlify.app`)
5. Klik **Deploy**

**Lewat CLI (alternatif):**
```bash
npm install -g vercel
vercel login
vercel        # ikutin prompt, pilih "Link to existing project" = No buat project baru
vercel env add GEMINI_API_KEY
vercel env add FIREBASE_SERVICE_ACCOUNT_KEY
vercel env add ALLOWED_ORIGINS
vercel --prod
```

Setelah deploy sukses, Vercel kasih URL kayak
`https://odyssey-backend.vercel.app` — pakai ini buat `ODYSSEY_BACKEND_URL`
di `report-agent.html`.

**Catatan:** Vercel serverless function itu "cold start" tiap request
setelah nganggur (mirip Render), tapi biasanya lebih cepat nyalanya
(hitungan detik, bukan puluhan detik). Timeout default function di plan
gratis 10 detik untuk Hobby (bisa sampai lebih lama tergantung
konfigurasi) — cukup buat 1 kali chat completion normal, tapi kalau
sering kena timeout pas mode report (thinking_level "low", token lebih
banyak), mungkin perlu dicek pengaturan `maxDuration` di `vercel.json`.

## Deploy ke Render (opsi alternatif)

Kalau suatu saat mau balik pakai Render (bukan Vercel):
1. Push folder ini ke repo Git
2. Di Render: New > Web Service > connect repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Isi Environment Variables yang sama seperti di atas

Atau pakai `render.yaml` yang udah disediakan lewat "New > Blueprint".

## Yang perlu diubah di sisi frontend (report-agent.html)

Ganti konstanta `ODYSSEY_BACKEND_URL` di `report-agent.html` jadi URL
Vercel yang baru. Fetch call-nya sendiri udah disesuaikan buat nyertain
Firebase ID Token:

```js
const idToken = await firebase.auth().currentUser.getIdToken();

const res = await fetch(ODYSSEY_BACKEND_URL + "/api/chat", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${idToken}`,
  },
  body: JSON.stringify({
    system: systemPrompt,
    contents: contents,
    max_tokens: 1000,
    thinking_level: "minimal",
    preferred_model: preferredModel,
  }),
});
```

## Belum dikerjain / perlu diperhatikan

- `require_access()` di `auth.py` masih placeholder — samain logicnya
  dengan `ACCESS_MAP` di `auth-guard.js` kalau Odyssey perlu whitelist
  email tertentu.
- Endpoint save/load chat history & memory facts (`save_chat_history`,
  `get_chat_history`, dst di `firebase_data.py`) sudah disiapkan
  fungsinya tapi belum di-wire ke endpoint FastAPI — tambahkan endpoint
  baru di `main.py` kalau mau logic sync-nya pindah ke backend (sekarang
  masih di localStorage + langsung dari client seperti sebelumnya).
- Fitur write-action (Update Stock, Submit Usage Log, Edit Jam Rest Time,
  dst) yang sekarang di JS client-side belum di-port — masih perlu
  diputuskan apakah write tetap dari client (pakai Realtime Database
  Rules yang sudah ada) atau dipindah lewat backend Python juga.

