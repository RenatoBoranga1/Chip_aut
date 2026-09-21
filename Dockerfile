FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY scanner_base scanner_base
COPY matching matching
COPY partners partners
COPY services services
COPY database database
COPY config config
ENTRYPOINT ["python", "-m", "app.import_base"]
