from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from app.api.auth.auth_controller import router as auth_router
from app.api.chat.chat_controller import router as chat_router
from app.api.voice.voice_controller import router as voice_router
from app.utils.response import error_response
from loguru import logger
from fastapi import status

def setup_routes(app: FastAPI):
    """Setup all routes for the application"""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == 404:
            # Now distinguish between route not found and explicit raise
            if exc.detail == "Not Found":
                # This is likely a route-missing 404 from FastAPI internals
                return await error_response("The requested resource was not found", status.HTTP_404_NOT_FOUND)
            else:
                # This is an explicit raise HTTPException(404) with custom detail
                logger.error(f"HTTP error: {exc.detail}")
                return await error_response(error=exc.detail, status_code=status.HTTP_404_NOT_FOUND)
        else:
            logger.error(f"HTTP error: {exc.detail}")
            return await error_response(error=exc.detail, status_code=exc.status_code)
    
    @app.exception_handler(405)
    async def method_not_allowed_handler(request: Request, exc: HTTPException):
        return await error_response(f"Method {request.method} not allowed for this endpoint", status.HTTP_405_METHOD_NOT_ALLOWED)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.error(f"Validation error: {exc.errors()}")
        if exc.errors():
            error = exc.errors()[0]

            # Prefer ctx['error'] if available
            if "ctx" in error and "error" in error["ctx"]:
                raw_error = error["ctx"]["error"]
                error_message = str(raw_error)
            else:
                field = error["loc"][-1] if error["loc"] else "unknown field"
                error_message = f"{field} {error['msg']}".lower()

        else:
            error_message = "Validation error"

        logger.error(f"Validation error: {error_message}")

        return await error_response(error_message, status.HTTP_422_UNPROCESSABLE_ENTITY)

    # Include all routes from the app
    app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
    app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
    app.include_router(voice_router, prefix="/api/voice", tags=["Voice"])
