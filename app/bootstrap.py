from app.main import app
from app.verification import router as verification_router

app.include_router(verification_router)
