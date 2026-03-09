from fastapi import APIRouter
from app.api.v1 import admin, auth, chats, glossary, messages

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(chats.router)
api_router.include_router(messages.router)
api_router.include_router(glossary.router)
api_router.include_router(admin.router)
