"""Data Peak FastAPI backend — Belgian company intelligence API."""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from routers import dashboard, screener, companies, stats, people, favourites, feedback, admin, polls

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
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Activity logging middleware
# ---------------------------------------------------------------------------

class ActivityLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Log authenticated API requests (not health checks or static)
        path = request.url.path
        if path.startswith("/api/") and path != "/api/health":
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                try:
                    from auth import _decode_token
                    payload = _decode_token(auth[7:])
                    email = payload.get("email", "unknown")
                    from db import execute
                    execute(
                        "INSERT INTO activity_log (user_email, endpoint, method) VALUES (%s, %s, %s)",
                        (email, path, request.method),
                    )
                except Exception:
                    pass  # Don't break requests if logging fails
        return response

app.add_middleware(ActivityLogMiddleware)

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

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "leadpeek-api"}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
