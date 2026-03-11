from fastapi import HTTPException, Request, FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from loguru import logger
from app.api.auth.token import JWTAuth
from app.utils.response import error_response

# Paths that don't require authentication
PUBLIC_PATHS = [
    "/docs",  # Swagger UI
    "/redoc",  # ReDoc UI
    "/openapi.json",  # OpenAPI schema
    "/api/auth/token",  # Token generation endpoint
    "/api/ws/voice",  # Voice WebSocket endpoint (WebSockets don't work with BaseHTTPMiddleware)
    "/health",  # Health check endpoint
]


class JWTAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, exclude_paths=None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or PUBLIC_PATHS
        self.valid_routes = None

    def get_valid_routes(self, app: FastAPI):
        """Extract all (path, method) pairs after app is fully initialized."""
        if self.valid_routes is None:
            self.valid_routes = set()
            for route in app.router.routes:
                if hasattr(route, "path") and hasattr(route, "methods"):
                    for method in route.methods:
                        self.valid_routes.add((route.path, method))
        return self.valid_routes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        request_path = request.url.path
        request_method = request.method
        logger.info(f"[JWT_MIDDLEWARE] Dispatch start | method={request_method} path={request_path}")

        # Ensure routes are extracted after app initialization
        valid_routes = self.get_valid_routes(request.app)
        logger.debug(f"[JWT_MIDDLEWARE] Valid routes cached={len(valid_routes)}")

        # If route does not match exactly, let FastAPI handle 404/405 naturally.
        if (request_path, request_method) not in valid_routes:
            if any(request_path == path for path, _ in valid_routes):
                logger.info(f"[JWT_MIDDLEWARE] Route found with different method | path={request_path} method={request_method}")
            else:
                logger.info(f"[JWT_MIDDLEWARE] Route not found | path={request_path} method={request_method}")
            return await call_next(request)

        # Allow public paths without authentication
        if any(request_path.startswith(path) for path in self.exclude_paths):
            logger.info(f"[JWT_MIDDLEWARE] Public path bypass | path={request_path}")
            return await call_next(request)

        # Validate Bearer token format and decode token.
        auth_header = request.headers.get("Authorization")
        logger.debug(f"[JWT_MIDDLEWARE] Authorization header present={bool(auth_header)}")

        try:
            user_id = JWTAuth.verify_token(auth_header)
        except HTTPException as e:
            logger.error(f"[JWT_MIDDLEWARE] JWT validation error | detail={str(e.detail)} status={e.status_code}")
            return await error_response(str(e.detail), e.status_code)
        except Exception as e:
            logger.exception(f"[JWT_MIDDLEWARE] Unexpected JWT verification error | error={str(e)}")
            return await error_response("Internal server error", 500)

        request.state.user_id = user_id
        logger.info(f"[JWT_MIDDLEWARE] Authenticated user | user_id={user_id}")
        return await call_next(request)
