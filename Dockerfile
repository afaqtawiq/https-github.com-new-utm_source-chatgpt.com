FROM node:22-alpine AS webbuild
WORKDIR /web
COPY web/package.json /web/package.json
RUN npm install --no-audit --no-fund
COPY web/retell-entry.js /web/retell-entry.js
RUN ./node_modules/.bin/esbuild retell-entry.js --bundle --format=esm --platform=browser --minify --outfile=retell-web-client.js

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
COPY --from=webbuild /web/retell-web-client.js /app/app/static/retell-web-client.js
EXPOSE 8000
CMD ["python","run_api.py"]
