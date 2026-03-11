from app.utils.response import error_response, success_response
from fastapi import APIRouter
from datetime import timedelta
from app.middleware.jwt_auth import JWTAuth
from app.api.auth.auth_model import TokenRequest, TokenResponse
from loguru import logger
from app.config import settings

router = APIRouter()

@router.post("/token", response_model=TokenResponse)
async def create_token(request: TokenRequest):
    """
    Create a new JWT token
    
    Parameters:
    - user_id: string - The user ID to encode in the token (3-50 chars, alphanumeric)
    
    Returns:
    - access_token: The generated JWT token
    - token_type: The type of token (bearer)
    """
    try:
        if settings.ENVIRONMENT.lower() == "production":
            return error_response("Requests are not allowed", 400)

        token = JWTAuth.create_token(
            {"user_id": request.user_id},
            expires_delta=timedelta(days=1)
        )
        return success_response(TokenResponse(access_token=token, token_type="bearer"), 200)
    except Exception as e:
        logger.error(f"Error creating token: {str(e)}")
        return error_response("Error creating token", 500)