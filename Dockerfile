FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir fastapi==0.115.12 uvicorn[standard]==0.34.2 httpx==0.28.1 pydantic==2.11.4
EXPOSE 8000
CMD ["python","run_api.py"]
