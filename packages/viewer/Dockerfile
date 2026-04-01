FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy SDK first (changes less often -> better layer caching)
COPY packages/sdk/ packages/sdk/
RUN pip install --no-cache-dir "packages/sdk[all]"

# Copy and install the viewer package
COPY packages/viewer/ packages/viewer/
RUN pip install --no-cache-dir --no-deps packages/viewer

# Create non-root user
RUN useradd -r -m -s /usr/sbin/nologin viewer && \
    mkdir -p /data && chown viewer:viewer /data

ENV MPLCONFIGDIR=/tmp/matplotlib

EXPOSE 8080
USER viewer

CMD ["python", "-m", "hangar.viewer.server"]
