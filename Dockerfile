FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY shawahid_app.py /app/shawahid_app.py
EXPOSE 8000
CMD ["uvicorn","shawahid_app:app","--host","0.0.0.0","--port","8000"]
