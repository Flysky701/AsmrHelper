"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.http.errors import register_error_handlers
from src.api.http.routes import (
    artifacts,
    asr,
    capabilities,
    inputs,
    llm,
    models,
    pipeline,
    pipeline_runs,
    resources,
    settings,
    sessions,
    subtitles,
    tasks,
    tool_runs,
    tools,
    translation,
    tts,
    voice,
    workspaces,
)


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
    app.include_router(pipeline.router, prefix=api_prefix)
    app.include_router(pipeline_runs.router, prefix=api_prefix)
    app.include_router(asr.router, prefix=api_prefix)
    app.include_router(llm.router, prefix=api_prefix)
    app.include_router(translation.router, prefix=api_prefix)
    app.include_router(tts.router, prefix=api_prefix)
    app.include_router(models.router, prefix=api_prefix)
    app.include_router(capabilities.router, prefix=api_prefix)
    app.include_router(workspaces.router, prefix=api_prefix)
    app.include_router(inputs.router, prefix=api_prefix)
    app.include_router(sessions.router, prefix=api_prefix)
    app.include_router(settings.router, prefix=api_prefix)
    app.include_router(subtitles.router, prefix=api_prefix)
    app.include_router(resources.router, prefix=api_prefix)
    app.include_router(tasks.router, prefix=api_prefix)
    app.include_router(artifacts.router, prefix=api_prefix)
    app.include_router(tool_runs.router, prefix=api_prefix)
    app.include_router(voice.router, prefix=api_prefix)
    app.include_router(tools.router, prefix=api_prefix)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.2.0"}

    return app
