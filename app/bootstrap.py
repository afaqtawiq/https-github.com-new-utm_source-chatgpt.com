from app.main import app
from app.verification import router as verification_router
from app.intelligence_ui import router as intelligence_router
from app.sales_copilot import router as sales_copilot_router
from app.outbound import router as outbound_router
from app.gmail_oauth import router as gmail_oauth_router
from app.revenue_sales import router as revenue_sales_router
from app.sales_workspace import router as sales_workspace_router
from app.followup_automation import router as followup_automation_router

app.include_router(verification_router)
app.include_router(intelligence_router)
app.include_router(sales_copilot_router)
app.include_router(outbound_router)
app.include_router(gmail_oauth_router)
app.include_router(revenue_sales_router)
app.include_router(sales_workspace_router)
app.include_router(followup_automation_router)
