from loguru import logger
from fastapi import Request


async def log_requests_middleware(request: Request, call_next):
    """Middleware to log API request lifecycle with execution time."""
    request_body = ""

    if request.method in ("POST", "PUT", "PATCH"):
        raw_body = await request.body()
        try:
            request_body = raw_body.decode("utf-8")
        except Exception:
            request_body = str(raw_body)

    logger.info(
        f"[REQUEST_MIDDLEWARE] Incoming request | method={request.method} path={request.url.path} "
        f"query={request.url.query} body_len={len(request_body)}"
    )

    try:
        response = await call_next(request)
        logger.info(
            f"[REQUEST_MIDDLEWARE] Completed request | method={request.method} "
            f"path={request.url.path} status={response.status_code}"
        )
        return response
    except Exception as e:
        logger.exception(
            f"[REQUEST_MIDDLEWARE] Request failed | method={request.method} "
            f"path={request.url.path} error={str(e)}"
        )
        raise
