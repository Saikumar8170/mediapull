from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = Path(os.environ.get("MEDIAPULL_DOWNLOAD_DIR", BASE_DIR / "downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

COOKIES_FILE = os.environ.get("MEDIAPULL_COOKIES", str(BASE_DIR / "cookies.txt"))
CACHE_TTL_SECONDS = int(os.environ.get("MEDIAPULL_CACHE_TTL", "2700"))  # 45 min
PROBE_TTL_SECONDS = 900  # 15 min
MAX_CONCURRENT_JOBS = int(os.environ.get("MEDIAPULL_MAX_JOBS", "3"))

YT_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
IG_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
}

MediaFormat = Literal["mp4", "mp3"]


def detect_platform(url: str) -> Literal["youtube", "instagram"]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a valid http(s) URL.")
    host = parsed.netloc.lower().split(":")[0]
    if host in YT_HOSTS:
        return "youtube"
    if host in IG_HOSTS:
        return "instagram"
    raise ValueError("Only YouTube and Instagram links are supported.")


def sanitize_filename(name: str, fallback: str = "media") -> str:
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]+', "", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:110].strip() or fallback)


def _common_ytdlp_flags() -> list[str]:
    flags = [
        "--no-playlist",
        "--no-warnings",
        "--concurrent-fragments",
        "8",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
    ]
    if COOKIES_FILE and Path(COOKIES_FILE).is_file():
        flags.extend(["--cookies", COOKIES_FILE])
    return flags


def _ytdlp_executable() -> str:
    venv_bin = Path(sys.executable).parent
    for candidate in ("yt-dlp.exe", "yt-dlp"):
        p = venv_bin / candidate
        if p.is_file():
            return str(p)
    found = shutil.which("yt-dlp")
    if found:
        return found
    return "yt-dlp"


@dataclass
class ProbeResult:
    url: str
    platform: Literal["youtube", "instagram"]
    title: str
    uploader: str
    duration: int | None
    thumbnail: str | None
    qualities: list[str]
    cached_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "platform": self.platform,
            "title": self.title,
            "uploader": self.uploader,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "qualities": self.qualities,
        }


@dataclass
class JobState:
    job_id: str
    url: str
    platform: Literal["youtube", "instagram"]
    fmt: MediaFormat
    quality: str
    stage: Literal["queued", "fetching", "downloading", "processing", "ready", "error"] = "queued"
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    title: str = ""
    file_path: Path | None = None
    download_name: str = ""
    file_size: int = 0
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    subscribers: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "platform": self.platform,
            "format": self.fmt,
            "quality": self.quality,
            "stage": self.stage,
            "percent": round(self.percent, 1),
            "speed": self.speed,
            "eta": self.eta,
            "title": self.title,
            "download_name": self.download_name,
            "file_size": self.file_size,
            "download_url": f"/api/download/{self.job_id}" if self.stage == "ready" else None,
            "error": self.error or None,
        }

    def publish(self) -> None:
        self.updated_at = time.time()
        payload = self.snapshot()
        for q in list(self.subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass


class MediaPipeline:
    def __init__(self) -> None:
        self.probe_cache: dict[str, ProbeResult] = {}
        self.jobs: dict[str, JobState] = {}
        self.result_cache: dict[tuple[str, MediaFormat, str], str] = {}  # key -> job_id
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    async def probe(self, url: str) -> ProbeResult:
        clean_url = url.strip()
        platform = detect_platform(clean_url)

        cached = self.probe_cache.get(clean_url)
        if cached and (time.time() - cached.cached_at) < PROBE_TTL_SECONDS:
            return cached

        cmd = [
            _ytdlp_executable(),
            "--dump-json",
            "--skip-download",
            *_common_ytdlp_flags(),
            clean_url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=35)
        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip().splitlines()
            detail = err_msg[-1] if err_msg else "Could not inspect link."
            raise RuntimeError(self._friendly_error(detail, platform))

        raw = stdout.decode("utf-8", errors="replace").strip().splitlines()[0]
        info = json.loads(raw)

        heights: set[int] = set()
        for f in info.get("formats") or []:
            h = f.get("height")
            vcodec = f.get("vcodec")
            if isinstance(h, int) and h >= 240 and vcodec and vcodec != "none":
                heights.add(h)

        standard = [2160, 1440, 1080, 720, 480, 360]
        available = [f"{h}p" for h in standard if any(x >= h - 40 for x in heights)]
        if not available:
            available = ["best"]

        result = ProbeResult(
            url=clean_url,
            platform=platform,
            title=info.get("title") or f"{platform.title()} Media",
            uploader=info.get("uploader") or info.get("channel") or "",
            duration=int(info["duration"]) if info.get("duration") else None,
            thumbnail=info.get("thumbnail"),
            qualities=available,
        )
        self.probe_cache[clean_url] = result
        return result

    async def start_job(self, url: str, fmt: MediaFormat, quality: str) -> JobState:
        clean_url = url.strip()
        platform = detect_platform(clean_url)
        norm_quality = quality.strip().lower()

        cache_key = (clean_url, fmt, norm_quality)
        cached_job_id = self.result_cache.get(cache_key)
        if cached_job_id:
            existing = self.jobs.get(cached_job_id)
            if (
                existing
                and existing.stage == "ready"
                and existing.file_path
                and existing.file_path.exists()
                and (time.time() - existing.updated_at) < CACHE_TTL_SECONDS
            ):
                return existing

        job_id = uuid.uuid4().hex[:12]
        cached_probe = self.probe_cache.get(clean_url)
        job = JobState(
            job_id=job_id,
            url=clean_url,
            platform=platform,
            fmt=fmt,
            quality=norm_quality,
            title=cached_probe.title if cached_probe else "",
        )
        self.jobs[job_id] = job
        asyncio.create_task(self._run_job(job, cache_key))
        return job

    async def _run_job(self, job: JobState, cache_key: tuple[str, MediaFormat, str]) -> None:
        async with self.semaphore:
            try:
                job.stage = "fetching"
                job.publish()

                if not job.title:
                    try:
                        probe = await self.probe(job.url)
                        job.title = probe.title
                        job.publish()
                    except Exception:
                        # Non-fatal: yt-dlp can still download even if pre-probe failed
                        pass

                out_template = str(DOWNLOAD_DIR / f"{job.job_id}.%(ext)s")
                cmd = [_ytdlp_executable(), *_common_ytdlp_flags(), "--newline"]

                if job.fmt == "mp3":
                    bitrate = re.sub(r"[^0-9]", "", job.quality) or "192"
                    if bitrate not in {"320", "256", "192", "128"}:
                        bitrate = "192"
                    cmd.extend([
                        "-f",
                        "ba/b",
                        "-x",
                        "--audio-format",
                        "mp3",
                        "--audio-quality",
                        f"{bitrate}K",
                    ])
                    tag = f"{bitrate}k"
                else:
                    height = re.sub(r"[^0-9]", "", job.quality)
                    if height:
                        fmt_selector = (
                            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
                            f"b[height<={height}][ext=mp4]/"
                            f"bv*[height<={height}]+ba/"
                            f"b[height<={height}]/b"
                        )
                        tag = f"{height}p"
                    else:
                        fmt_selector = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
                        tag = "best"
                    cmd.extend([
                        "-f",
                        fmt_selector,
                        "--merge-output-format",
                        "mp4",
                    ])

                cmd.extend([
                    "--progress-template",
                    "download:MP_PROG|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
                    "-o",
                    out_template,
                    job.url,
                ])

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )

                last_lines: list[str] = []
                assert proc.stdout is not None
                while True:
                    line_bytes = await proc.stdout.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    if line.startswith("MP_PROG|"):
                        parts = line.split("|")
                        if len(parts) >= 4:
                            pct_raw = parts[1].replace("%", "").strip()
                            try:
                                job.percent = max(0.0, min(99.0, float(pct_raw)))
                            except ValueError:
                                pass
                            job.speed = parts[2].strip() if parts[2].strip() != "N/A" else ""
                            job.eta = parts[3].strip() if parts[3].strip() != "N/A" else ""
                            job.stage = "downloading"
                            job.publish()
                    else:
                        last_lines.append(line)
                        if len(last_lines) > 12:
                            last_lines.pop(0)
                        if (
                            "[Merger]" in line
                            or "[ExtractAudio]" in line
                            or "[ffmpeg]" in line
                            or "Fixing" in line
                        ):
                            job.stage = "processing"
                            job.percent = 99.0
                            job.speed = ""
                            job.eta = ""
                            job.publish()

                rc = await proc.wait()
                if rc != 0:
                    err_text = last_lines[-1] if last_lines else "Conversion failed."
                    raise RuntimeError(self._friendly_error(err_text, job.platform))

                target = DOWNLOAD_DIR / f"{job.job_id}.{job.fmt}"
                if not target.exists():
                    matches = list(DOWNLOAD_DIR.glob(f"{job.job_id}.*"))
                    if not matches:
                        raise RuntimeError("Output file was not produced.")
                    target = matches[0]

                base_name = sanitize_filename(job.title or f"{job.platform}_{job.job_id}")
                job.file_path = target
                job.file_size = target.stat().st_size
                job.download_name = f"{base_name} [{tag}].{target.suffix.lstrip('.')}"
                job.stage = "ready"
                job.percent = 100.0
                job.speed = ""
                job.eta = ""
                self.result_cache[cache_key] = job.job_id
                job.publish()

            except Exception as exc:
                job.stage = "error"
                job.error = str(exc)
                job.publish()

    @staticmethod
    def _friendly_error(raw: str, platform: str) -> str:
        low = raw.lower()
        if "login" in low or "cookies" in low or "sign in" in low:
            return f"{platform.title()} requested authentication for this link (private or rate-limited)."
        if "private" in low or "unavailable" in low:
            return "This media is private or unavailable."
        if "unsupported url" in low:
            return "Unsupported or malformed link."
        return raw

    async def cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            now = time.time()
            expired_ids = [
                jid
                for jid, j in self.jobs.items()
                if (now - j.updated_at) > CACHE_TTL_SECONDS
            ]
            for jid in expired_ids:
                job = self.jobs.pop(jid, None)
                if job and job.file_path and job.file_path.exists():
                    try:
                        job.file_path.unlink()
                    except OSError:
                        pass
            for k, jid in list(self.result_cache.items()):
                if jid not in self.jobs:
                    self.result_cache.pop(k, None)
            for k, p in list(self.probe_cache.items()):
                if (now - p.cached_at) > PROBE_TTL_SECONDS:
                    self.probe_cache.pop(k, None)


pipeline = MediaPipeline()
