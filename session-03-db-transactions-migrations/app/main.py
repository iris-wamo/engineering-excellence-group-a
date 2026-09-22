from fastapi import FastAPI

from app.api.v1.routes.imports import router as imports_router
from app.api.v1.routes.projects import router as projects_router
from app.api.v1.routes.tasks import router as tasks_router
from app.api.v1.routes.users import router as users_router

app = FastAPI(
    title="TaskFlow API",
    description="Internal Team Work Management Backend — Session 3: Database & Import Pipeline",
    version="0.3.0",
)

app.include_router(users_router)
app.include_router(tasks_router)
app.include_router(projects_router)
app.include_router(imports_router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
