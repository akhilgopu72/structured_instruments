import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _start_gmail_poller() -> None:
    """Sync offering emails every SI_GMAIL_POLL_MINUTES (default 30; 0 disables)."""
    from structured_instruments.api.routers.candidates import run_gmail_sync_in_background

    minutes = float(os.environ.get("SI_GMAIL_POLL_MINUTES", "30"))
    if minutes <= 0:
        return

    def loop() -> None:
        while True:
            run_gmail_sync_in_background()  # no-op until `si gmail auth` has been run
            time.sleep(minutes * 60)

    threading.Thread(target=loop, daemon=True, name="gmail-poller").start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_gmail_poller()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Structured Instruments API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Include all routers
    from structured_instruments.api.routers import (
        instruments,
        dashboard,
        coupons,
        performance,
        prices,
        refresh,
        export,
        users,
        accounts,
        upload,
        candidates,
    )

    app.include_router(users.router)
    app.include_router(accounts.router)
    app.include_router(instruments.router)
    app.include_router(dashboard.router)
    app.include_router(coupons.router)
    app.include_router(performance.router)
    app.include_router(prices.router)
    app.include_router(refresh.router)
    app.include_router(export.router)
    app.include_router(upload.router)
    app.include_router(candidates.router)
    return app


app = create_app()
