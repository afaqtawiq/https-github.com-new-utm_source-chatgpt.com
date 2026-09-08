import os
import uvicorn
from app.main import app
from app.discovery_ui import router as discovery_router

app.include_router(discovery_router)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT','8000')), proxy_headers=True, forwarded_allow_ips='*')
