"""Data Peak FastAPI backend — Belgian company intelligence API."""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from routers import dashboard, screener, companies, stats, people, favourites, feedback, admin, polls, stripe_pay, staatsblad
from rate_limit import limiter, get_client_ip

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Data Peak API",
    description="Belgian company intelligence — KBO registry + NBB annual accounts",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://datapeak.invm.be", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---------------------------------------------------------------------------
# Activity logging middleware
# ---------------------------------------------------------------------------

class ActivityLogMiddleware(BaseHTTPMiddleware):
    SKIP_PATHS = ("/api/health", "/api/polls/active", "/api/dashboard")

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/") and path not in self.SKIP_PATHS:
            try:
                from db import execute
                email = None
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    try:
                        from auth import _decode_token
                        payload = _decode_token(auth[7:])
                        email = payload.get("email")
                        if email:
                            execute(
                                "INSERT INTO user_roles (email, role) VALUES (%s, 'user') ON CONFLICT (email) DO NOTHING",
                                (email,),
                            )
                    except Exception:
                        pass

                # Log for both authenticated and anonymous users
                # Anonymous: store IP as "anon:<ip>"
                user_label = email or f"anon:{get_client_ip(request)}"
                execute(
                    "INSERT INTO activity_log (user_email, endpoint, method) VALUES (%s, %s, %s)",
                    (user_label, path, request.method),
                )
            except Exception:
                pass
        return response

app.add_middleware(ActivityLogMiddleware)

# ---------------------------------------------------------------------------
# Rate limiting middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting keyed by authenticated user email or client IP."""

    SEARCH_PATHS = ("/api/companies/search", "/api/people/search")

    def _get_rate_key(self, request: Request) -> str:
        """Get rate limit key: prefer auth user email, fall back to real IP."""
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                from auth import _decode_token
                payload = _decode_token(auth[7:])
                email = payload.get("email")
                if email:
                    return f"user:{email}"
            except Exception:
                pass
        return f"ip:{get_client_ip(request)}"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        if not path.startswith("/api/"):
            return await call_next(request)

        key = self._get_rate_key(request)

        try:
            # Search endpoints: 60/min per user
            if any(path.startswith(p) for p in self.SEARCH_PATHS):
                limiter.check(key, max_requests=60, window_seconds=60)
            # All other API calls: 200/min per user
            else:
                limiter.check(key, max_requests=200, window_seconds=60)
        except Exception as e:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=429, content={"detail": str(e.detail) if hasattr(e, "detail") else "Rate limit exceeded"})

        return await call_next(request)

app.add_middleware(RateLimitMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(dashboard.router)
app.include_router(screener.router)
app.include_router(companies.router)
app.include_router(stats.router)
app.include_router(people.router)
app.include_router(favourites.router)
app.include_router(feedback.router)
app.include_router(admin.router)
app.include_router(polls.router)
app.include_router(stripe_pay.router)
app.include_router(staatsblad.router)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "datapeak-api"}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
