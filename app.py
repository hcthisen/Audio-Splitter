from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from pydub import AudioSegment
import base64, io, math, uvicorn

app = FastAPI(title="Audio Splitter API")

@app.get("/health")
def health():
    return {"status": "ok"}

SUPPORTED_EXPORTS = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg"}

@app.post("/split")
async def split_audio(
    file: UploadFile = File(...),
    chunk_ms: int = Form(600_000),        # 10 minutes default
    overlap_ms: int = Form(0),
    export_format: str = Form("mp3")      # mp3|wav|flac|ogg
):
    if export_format not in SUPPORTED_EXPORTS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {export_format}")

    if chunk_ms <= 0 or overlap_ms < 0 or overlap_ms >= chunk_ms:
        raise HTTPException(status_code=400, detail="Invalid chunk/overlap values")

    # Read bytes into AudioSegment
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
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

    return JSONResponse({"chunks": chunks_json, "total_duration_ms": duration, "chunk_ms": chunk_ms, "overlap_ms": overlap_ms, "format": export_format})
    
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
