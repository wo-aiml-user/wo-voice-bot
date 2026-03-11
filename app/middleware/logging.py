import time
from loguru import logger
from fastapi import Request

async def log_requests_middleware(request: Request, call_next):
    """Middleware to log the full API request with execution time"""

    start_time = time.time()
    request_body = None
    if request.method in ("POST", "PUT", "PATCH"):
        request_body = await request.body()
        try:
            request_body = request_body.decode("utf-8")
        except Exception:
            request_body = str(request_body)
    else:
        request_body = ""

    # logger.info(
    #         f"Request: {request.method} {request.url.path} | Body: {request_body}"
    #     )

    response = await call_next(request)
    duration = (time.time() - start_time) * 1000
    logger.info(f"API: {request.method} {request.url.path} | Status: {response.status_code} | Time: {duration:.2f}ms")
    return response