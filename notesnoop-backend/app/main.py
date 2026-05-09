from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import bootstrap, graph, notes, webhooks


app = FastAPI(title="NoteSnoop API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://notesnoop.app", "https://staging.notesnoop.app", "http://localhost:3010"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "notesnoop-backend"}


app.include_router(bootstrap.router)
app.include_router(graph.router)
app.include_router(notes.router)
app.include_router(webhooks.router)
