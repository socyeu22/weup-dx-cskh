import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CSKH bot starting up")
    yield
    logger.info("CSKH bot shutting down")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/pancake")
async def webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    channel = body.get("data", {}).get("conversation", {}).get("type", "")
    psid = body.get("data", {}).get("conversation", {}).get("from", {}).get("id", "")
    logger.info(f"webhook received channel={channel} psid={psid}")

    # Phase 1: accept và log, chưa xử lý
    # Phase 2+ sẽ invoke graph ở đây
    return {"status": "accepted"}


@app.post("/admin/reset/{psid}")
async def reset_handoff(psid: str):
    # TODO Phase 2: kết nối postgres_store
    logger.info(f"reset_handoff psid={psid}")
    return {"status": "ok", "psid": psid}
