"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.http.errors import register_error_handlers
from src.api.http.routes import asr, jobs, models, pipeline, resources, subtitles, tasks, tools, translation, tts, voice


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="ASMR Helper API",
        description="HTTP API for ASMR Helper audio processing pipeline",
        version="0.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Error handlers
    register_error_handlers(app)

    # Routes
    api_prefix = "/api/v1"
    app.include_router(jobs.router, prefix=api_prefix)
    app.include_router(pipeline.router, prefix=api_prefix)
    app.include_router(asr.router, prefix=api_prefix)
    app.include_router(translation.router, prefix=api_prefix)
    app.include_router(tts.router, prefix=api_prefix)
    app.include_router(models.router, prefix=api_prefix)
    app.include_router(subtitles.router, prefix=api_prefix)
    app.include_router(resources.router, prefix=api_prefix)
    app.include_router(tasks.router, prefix=api_prefix)
    app.include_router(voice.router, prefix=api_prefix)
    app.include_router(tools.router, prefix=api_prefix)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.2.0"}

    return app
