from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .pipeline import MediaFormat, pipeline

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(pipeline.cleanup_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="MediaPull", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProbeRequest(BaseModel):
    url: str


class ConvertRequest(BaseModel):
    url: str
    format: MediaFormat
    quality: str = "1080p"


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/probe")
async def probe_media(req: ProbeRequest):
    try:
        res = await pipeline.probe(req.url)
        return res.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Timed out while reading link metadata.") from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/convert")
async def convert_media(req: ConvertRequest):
    try:
        job = await pipeline.start_job(req.url, req.format, req.quality)
        return job.snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = pipeline.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    return job.snapshot()


@app.get("/api/events/{job_id}")
async def job_events(job_id: str):
    job = pipeline.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired.")

    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=32)
    job.subscribers.append(queue)

    async def event_stream():
        try:
            # Emit current state immediately
            yield f"data: {json.dumps(job.snapshot())}\n\n"
            if job.stage in {"ready", "error"}:
                return

            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("stage") in {"ready", "error"}:
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if queue in job.subscribers:
                job.subscribers.remove(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/download/{job_id}")
async def download_file(job_id: str):
    job = pipeline.jobs.get(job_id)
    if not job or job.stage != "ready" or not job.file_path or not job.file_path.exists():
        raise HTTPException(status_code=404, detail="File not ready or expired.")

    media_type = "audio/mpeg" if job.fmt == "mp3" else "video/mp4"
    return FileResponse(
        path=job.file_path,
        media_type=media_type,
        filename=job.download_name,
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html")
