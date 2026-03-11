import tempfile
from contextlib import asynccontextmanager
from fastapi import FastAPI
from loguru import logger
from app.config import settings
from app.middleware import setup_middlewares
from app.route import setup_routes
from app.logger import setup_logger
from app.RAG.vector_store import (
    connect_to_mongodb, disconnect_from_mongodb,
)
import os
import socket
from filelock import FileLock, Timeout

LOCK_FILE = os.path.join(tempfile.gettempdir(), "rag_worker.lock")


@asynccontextmanager
async def lifespan(app: FastAPI):
    hostname, worker_id = socket.gethostname(), os.getpid()
    logger.info(f"Worker starting: host={hostname}, pid={worker_id}")

    lock = FileLock(LOCK_FILE)        # always build the lock, file may pre-exist
    try:
        lock.acquire(timeout=0)       # non-blocking try
        is_primary = True
        try:
            with open(LOCK_FILE, "w") as f:
                f.write(f"{hostname}:{worker_id}")
        except IOError as e:
            logger.warning(f"Failed to write lock file: {e}")

        # primary initialisation
        await connect_to_mongodb()
        # app.state.sqs_task = asyncio.create_task(consume_forever())

    except Timeout:
        is_primary = False
        logger.info(f"{hostname}:{worker_id} is SECONDARY (lock busy)")
        await connect_to_mongodb()

    # ── FastAPI runs ────────────────────────────────────────────
    yield
    # ── Shutdown ────────────────────────────────────────────────
    if is_primary:
        logger.info("Primary shutting down")
        # task = app.state.get("sqs_task")
        # if task:
        #     task.cancel()
        #     try:
        #         await task
        #     except asyncio.CancelledError:
        #         pass
        lock.release()
        try:
            os.remove(LOCK_FILE)
        except FileNotFoundError:
            pass
        logger.info("Released lock and cleaned up")
    else:
        logger.info("Secondary shutting down")

    await disconnect_from_mongodb()
    logger.info("RAG system disconnected")


# ─────────────── FastAPI app object ───────────────────────────
app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)

setup_logger(settings)
setup_middlewares(app)
setup_routes(app)
