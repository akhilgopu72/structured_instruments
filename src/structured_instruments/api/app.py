from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="Structured Instruments API")
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
    return app


app = create_app()
