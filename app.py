from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from pydub import AudioSegment
import base64, io, math, uvicorn, os
import httpx

app = FastAPI(title="Audio Splitter API")

@app.get("/health")
def health():
    return {"status": "ok"}

SUPPORTED_EXPORTS = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg"}

MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "200"))  # guardrail for URL mode

@app.post("/split")
async def split_audio(
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    chunk_ms: int = Form(600_000),
    overlap_ms: int = Form(0),
    export_format: str = Form("mp3")
):
    if export_format not in SUPPORTED_EXPORTS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {export_format}")
    if chunk_ms <= 0 or overlap_ms < 0 or overlap_ms >= chunk_ms:
        raise HTTPException(status_code=400, detail="Invalid chunk/overlap values")

    # ---- read bytes from either an uploaded file or a URL ----
    raw: bytes | None = None
    if file is not None:
        raw = await file.read()
    elif url:
        # Stream download with size cap
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream("GET", url, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    chunks = []
                    total = 0
                    limit = MAX_DOWNLOAD_MB * 1024 * 1024
                    async for part in resp.aiter_bytes():
                        total += len(part)
                        if total > limit:
                            raise HTTPException(status_code=413, detail=f"Remote file exceeds {MAX_DOWNLOAD_MB} MB limit")
                        chunks.append(part)
                    raw = b"".join(chunks)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to download URL: {e}")
    else:
        raise HTTPException(status_code=422, detail="Provide either a file upload or a url")

    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio data")

    # ---- decode & split ----
    try:
        audio = AudioSegment.from_file(io.BytesIO(raw))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not decode audio: {e}")

    duration = len(audio)  # ms
    step = chunk_ms - overlap_ms
    n = max(1, math.ceil((max(1, duration - overlap_ms)) / step))

    chunks_json = []
    for i in range(n):
        start = max(0, i * step)
        end = min(duration, start + chunk_ms)
        segment = audio[start:end]

        buf = io.BytesIO()
        segment.export(buf, format=export_format)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        chunks_json.append({
            "index": i,
            "start_ms": start,
            "end_ms": end,
            "mime": SUPPORTED_EXPORTS[export_format],
            "data_base64": b64
        })

    return JSONResponse({
        "source": "upload" if file is not None else "url",
        "chunks": chunks_json,
        "total_duration_ms": duration,
        "chunk_ms": chunk_ms,
        "overlap_ms": overlap_ms,
        "format": export_format
    })
