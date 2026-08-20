"""
RouteEase structured error handling.
All errors follow the standard contract: {"error": {"code": "...", "message": "...", "request_id": "..."}}.
"""
from __future__ import annotations
from typing import Optional

from enum import Enum

from fastapi import Request
from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    """Standard error codes exposed to the frontend."""
    VALIDATION_ERROR = "VALIDATION_ERROR"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
    ROUTING_API_ERROR = "ROUTING_API_ERROR"
    PITSTOP_API_ERROR = "PITSTOP_API_ERROR"
    LLM_ERROR = "LLM_ERROR"
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RouteEaseError(Exception):
    """Base exception for RouteEase errors."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 500,
        request_id: Optional[str] = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(message)


class ValidationError(RouteEaseError):
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(ErrorCode.VALIDATION_ERROR, message, 422, request_id)


class RouteNotFoundError(RouteEaseError):
    def __init__(self, message: str = "No suitable route could be found.", request_id: Optional[str] = None):
        super().__init__(ErrorCode.ROUTE_NOT_FOUND, message, 404, request_id)


class RoutingAPIError(RouteEaseError):
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(ErrorCode.ROUTING_API_ERROR, message, 502, request_id)


class PitstopAPIError(RouteEaseError):
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(ErrorCode.PITSTOP_API_ERROR, message, 502, request_id)


class LLMError(RouteEaseError):
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(ErrorCode.LLM_ERROR, message, 502, request_id)


class LLMInvalidResponseError(RouteEaseError):
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(ErrorCode.LLM_INVALID_RESPONSE, message, 502, request_id)


class ConfigurationError(RouteEaseError):
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(ErrorCode.CONFIGURATION_ERROR, message, 500, request_id)


def error_response(code: ErrorCode, message: str, status_code: int, request_id: Optional[str] = None) -> JSONResponse:
    """Build a standard error JSON response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code.value,
                "message": message,
                "request_id": request_id,
            }
        },
    )


async def routeease_exception_handler(_request: Request, exc: RouteEaseError) -> JSONResponse:
    """FastAPI exception handler for RouteEaseError."""
    return error_response(exc.code, exc.message, exc.status_code, exc.request_id)
