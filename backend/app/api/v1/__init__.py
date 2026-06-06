"""
API v1 package — exports the router used by main.py.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import router as endpoints_router

router = APIRouter()
router.include_router(endpoints_router)
