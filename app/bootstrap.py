from app.main import app
from app.verification import router as verification_router
from app.intelligence_ui import router as intelligence_router
from app.sales_copilot import router as sales_copilot_router
from app.outbound import router as outbound_router
from app.gmail_oauth import router as gmail_oauth_router
from app.revenue_sales import router as revenue_sales_router
from app.sales_workspace import router as sales_workspace_router
from app.followup_automation import router as followup_automation_router
from app.inbound_sales import router as inbound_sales_router
from app.inbound_actions import router as inbound_actions_router
from app.quote_builder import router as quote_builder_router
from app.quote_pricing import router as quote_pricing_router
from app.quote_workflow import router as quote_workflow_router
from app.operations_control import router as operations_control_router
from app.control_tower import router as control_tower_router
from app.ceo_command import router as ceo_command_router
from app.customer360 import router as customer360_router
from app.customer_success import router as customer_success_router
from app.revenue_growth import router as revenue_growth_router
from app.management_autopilot import router as management_autopilot_router

app.include_router(verification_router)
app.include_router(intelligence_router)
app.include_router(sales_copilot_router)
app.include_router(outbound_router)
app.include_router(gmail_oauth_router)
app.include_router(revenue_sales_router)
app.include_router(sales_workspace_router)
app.include_router(followup_automation_router)
app.include_router(inbound_sales_router)
app.include_router(inbound_actions_router)
app.include_router(quote_builder_router)
app.include_router(quote_pricing_router)
app.include_router(quote_workflow_router)
app.include_router(operations_control_router)
app.include_router(control_tower_router)
app.include_router(ceo_command_router)
app.include_router(customer360_router)
app.include_router(customer_success_router)
app.include_router(revenue_growth_router)
app.include_router(management_autopilot_router)
