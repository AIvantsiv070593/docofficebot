FROM python:3.12-slim
# Image stays on 3.12; local host may use 3.9+

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libheif1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data

VOLUME ["/app/data"]

CMD ["python", "-m", "src.main"]
