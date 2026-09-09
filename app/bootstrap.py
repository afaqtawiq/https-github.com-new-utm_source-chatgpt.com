from fastapi.responses import JSONResponse,RedirectResponse
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
from app.security_governance import router as security_governance_router,csrf_guard
from app.team_rbac import router as team_rbac_router
from app.identity_hardening import router as identity_hardening_router
from app.fine_permissions import router as fine_permissions_router,has_permission
from app import mfa_schema_compat
from app import mfa_recovery  # initialize MFA attempt storage; recovery routes stay disabled
from app.mfa_stepup import router as mfa_stepup_router,mfa_state,recent_stepup
from app.security_operations import router as security_operations_router
from app.incident_response import router as incident_response_router
from app.retell_integration import router as retell_integration_router
from app.phone_sales import router as phone_sales_router
from app.crm_contacts import router as crm_contacts_router
from app.data_import import router as data_import_router
from app.drivers_management import router as drivers_management_router
from app.storage import get_session,one,execute,utcnow
ROLE_PREFIX={'admin':None,'sales':('/operations','/control-tower','/security','/soc','/incidents','/team','/permissions'),'customs':('/sales-center','/sales-copilot','/outbound','/quotes','/quote-workflow','/revenue-growth','/customer-success','/security','/soc','/incidents','/team','/permissions','/phone-sales','/crm/contacts'),'transport':('/sales-center','/sales-copilot','/outbound','/quotes','/quote-workflow','/revenue-growth','/customer-success','/security','/soc','/incidents','/team','/permissions','/phone-sales','/crm/contacts'),'finance':('/operations','/control-tower','/outbound','/sales-inbox','/security','/soc','/incidents','/team','/permissions','/phone-sales','/crm/contacts'),'viewer':()}
SENSITIVE=[('send_email','POST','/outbound/','/send'),('approve_quote','POST','/quotes/','/approve-commercial'),('approve_pricing','POST','/quotes/','/approve-pricing'),('accept_quote','POST','/quotes/','/accept'),('manage_gmail','POST','/settings/email',''),('manage_users','POST','/team/',''),('edit_operations','POST','/operations/',''),('edit_operations','POST','/control-tower/','')]
def role_allowed(request,s):
 if not s:return True
 role=s.get('role','viewer');path=request.url.path
 if role=='admin':return True
 if role=='viewer':return request.method in ('GET','HEAD','OPTIONS') and path not in ('/security','/soc','/incidents','/team','/permissions') and not path.startswith('/auth/google')
 return not any(path==p or path.startswith(p+'/') for p in ROLE_PREFIX.get(role,()))
def sensitive_permission(request):
 path=request.url.path
 for perm,method,prefix,suffix in SENSITIVE:
  if request.method==method and path.startswith(prefix) and (not suffix or path.endswith(suffix)):return perm
 return None
@app.middleware('http')
async def enterprise_security_guard(request,call_next):
 if request.url.path!='/webhooks/retell' and not csrf_guard(request):
  code=429 if request.url.path=='/login' else 403;return JSONResponse({'detail':'Too many login requests' if code==429 else 'Cross-site mutation blocked'},status_code=code)
 sess=get_session(request.cookies.get('gla_session'))
 if sess:
  u=one('SELECT is_active,must_change_password FROM users WHERE id=?',(sess['user_id'],))
  if not u or not u.get('is_active',1):execute('DELETE FROM sessions WHERE id=?',(sess['id'],));return RedirectResponse('/login',303)
  execute('UPDATE sessions SET last_seen_at=? WHERE id=?',(utcnow(),sess['id']))
  if u.get('must_change_password') and not (request.url.path.startswith('/identity') or request.url.path.startswith('/mfa') or request.url.path in ('/logout','/api/v50/health')):return RedirectResponse('/identity',303)
 if not role_allowed(request,sess):return JSONResponse({'detail':'Role does not permit this action'},status_code=403)
 perm=sensitive_permission(request)
 if perm and sess:
  if not has_permission(sess,perm):return JSONResponse({'detail':'Permission does not permit this action','permission':perm},status_code=403)
  m=mfa_state(sess['user_id'])
  if not m or not m.get('mfa_enabled'):return JSONResponse({'detail':'MFA enrollment required for this sensitive action','mfa_setup':'/mfa','permission':perm},status_code=428)
  if not recent_stepup(sess['id']):return JSONResponse({'detail':'Recent MFA step-up required','step_up':'/mfa/step-up?next='+request.url.path,'permission':perm},status_code=428)
 response=await call_next(request);response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY';response.headers['Referrer-Policy']='same-origin';response.headers['Permissions-Policy']='camera=(), microphone=(self), geolocation=()' if request.url.path=='/retell-web-test' else 'camera=(), microphone=(), geolocation=()';return response
for r in (verification_router,intelligence_router,sales_copilot_router,outbound_router,gmail_oauth_router,revenue_sales_router,sales_workspace_router,followup_automation_router,inbound_sales_router,inbound_actions_router,quote_builder_router,quote_pricing_router,quote_workflow_router,operations_control_router,control_tower_router,ceo_command_router,customer360_router,customer_success_router,revenue_growth_router,management_autopilot_router,security_governance_router,team_rbac_router,identity_hardening_router,fine_permissions_router,mfa_stepup_router,security_operations_router,incident_response_router,retell_integration_router,phone_sales_router,crm_contacts_router):app.include_router(r)
app.include_router(data_import_router)
app.include_router(drivers_management_router)
