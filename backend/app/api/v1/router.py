from fastapi import APIRouter

from app.api.v1.routes import admin, agent, auth, common, member, workspace


router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["authentication"])
router.include_router(common.router, tags=["shared"])
router.include_router(workspace.router, tags=["workspace"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
router.include_router(agent.router, prefix="/agent", tags=["agent"])
router.include_router(member.router, prefix="/member", tags=["member"])
