from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.responses import Response


class JsonCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code < 400:
            return response
        headers = {
            name: value
            for name, value in response.headers.items()
            if name not in {"content-type", "content-length"}
        }
        return JSONResponse(
            status_code=response.status_code,
            content={"detail": "origin, method, or headers not allowed"},
            headers=headers,
        )
