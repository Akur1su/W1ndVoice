FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

ENV W1NDVOICE_HOST=0.0.0.0 \
    W1NDVOICE_PORT=8000 \
    W1NDVOICE_DATA_DIR=/app/data

VOLUME ["/app/data"]
EXPOSE 8000
CMD ["w1ndvoice"]
