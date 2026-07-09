from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mongoengine import DoesNotExist, ValidationError


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "bad_request") -> None:
        self.message = message
        self.status_code = status_code
        self.code = code


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message=message, status_code=404, code="not_found")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(DoesNotExist)
    async def handle_does_not_exist(_: Request, exc: DoesNotExist) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": str(exc) or "Resource not found"}},
        )

    @app.exception_handler(ValidationError)
    async def handle_mongo_validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": str(exc)}},
        )
