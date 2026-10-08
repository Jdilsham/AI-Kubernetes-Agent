# kubectl in its own stage: keeps curl/ca-certificates out of the final image entirely.
FROM debian:bookworm-slim AS kubectl
ARG KUBECTL_VERSION=v1.37.1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSLo /usr/local/bin/kubectl \
       "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/$(dpkg --print-architecture)/kubectl" \
    && chmod +x /usr/local/bin/kubectl

FROM python:3.12-slim AS deps
WORKDIR /app
COPY requirements.txt .
# Plain `uvicorn` (no [standard] extras): the app uses neither uvloop, websockets nor auto-reload.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Jdilsham/AI-Kubernetes-Agent" \
      org.opencontainers.image.description="AI Kubernetes Agent backend" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY --from=kubectl /usr/local/bin/kubectl /usr/local/bin/kubectl
COPY --from=deps /install /usr/local
COPY app ./app

# Non-root user; /data holds the SQLite history (mounted as a volume in Kubernetes)
RUN useradd --uid 10001 --create-home agent && mkdir -p /data && chown agent /data
USER 10001

EXPOSE 9000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
