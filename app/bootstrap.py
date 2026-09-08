from app.main import app
from app.verification import router as verification_router
from app.intelligence_ui import router as intelligence_router

app.include_router(verification_router)
app.include_router(intelligence_router)
