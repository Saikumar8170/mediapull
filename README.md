---
title: MediaPull
emoji: ⚡
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# MEDIAPULL

Fast YouTube & Instagram to MP4 / MP3 converter powered by FastAPI, `yt-dlp`, and `ffmpeg` with live SSE progress streaming.

## Run Locally (Windows)

```powershell
.\start.ps1
```

Open `http://localhost:8000`.

## Free Permanent URL (Works on Any Device, Even After Days)

### Option A: Cloud Hosting (No PC Needed) — Hugging Face Spaces (Free)
1. Create a free account at `https://huggingface.co`.
2. Create a new **Space** -> choose **Docker** (Blank) -> Public or Private.
3. Upload this folder (specifically `Dockerfile`, `requirements.txt`, and `app/`).
4. Your permanent, memorable HTTPS URL will be:
   `https://<your-username>-<space-name>.hf.space`
   It stays on that exact URL permanently and works on phones, tablets, and desktops.

### Option B: Your Own PC + ngrok Free Static Domain (Best for YouTube Reliability)
Cloud datacenter IPs are sometimes rate-limited by YouTube. Running on your PC with ngrok's **1 free permanent static domain** avoids datacenter blocks and keeps the exact same URL forever:
1. Create a free account at `https://ngrok.com` and claim your free static domain (e.g. `my-mediapull.ngrok-free.app`).
2. Install ngrok (`winget install ngrok.ngrok`) and run `ngrok config add-authtoken <YOUR_TOKEN>`.
3. Start MediaPull (`.\start.ps1`) and run:
   ```powershell
   ngrok http --url=my-mediapull.ngrok-free.app 8000
   ```
