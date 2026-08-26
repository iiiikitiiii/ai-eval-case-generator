from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import agents, auth, board, cases, health, settings as settings_router
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One Redis connection pool for the app's lifetime, used to enqueue
    # pipeline-step jobs onto the arq worker (app/workers/worker.py).
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        yield
    finally:
        await app.state.arq_pool.close()


app = FastAPI(title="Case Pipeline Hub API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(agents.router)
app.include_router(board.router)
app.include_router(settings_router.router)

# Phase 3: regression-suite router still open (golden-case runs, publish gate)
# Phase 5: audit log usage, compliance-tightened storage (async queue is done)
