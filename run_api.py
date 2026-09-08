import os
import uvicorn
if __name__ == '__main__':
    uvicorn.run('app.bootstrap:app', host='0.0.0.0', port=int(os.getenv('PORT','8000')), proxy_headers=True, forwarded_allow_ips='*')
