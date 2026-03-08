from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.automation import router as automation_router
from app.api.jobs import router as jobs_router, warm_startup_caches
from app.api.profile import router as profile_router
from app.core.config import settings
from app.db.migrations import run_migrations
from app.db.session import Base, engine
from app.models import automation_run, job, job_material, job_source, profile, refresh_state  # noqa: F401
from app.services.background_refresh import start_refresh_queue, stop_refresh_queue
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    start_refresh_queue()
    start_scheduler()
    try:
        await warm_startup_caches()
        yield
    finally:
        stop_scheduler()
        stop_refresh_queue()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(jobs_router)
app.include_router(automation_router)
app.include_router(profile_router)
