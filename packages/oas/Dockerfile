FROM python:3.11-slim

# System dependencies for numpy/scipy (BLAS/LAPACK) and compiled extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        gfortran \
        git \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install OpenAeroStruct from upstream at a pinned ref.
# Default tracks scripts/upstream-pins.env (OAS_REF); bump both together.
# Override at build time: --build-arg OAS_REF=<commit|tag|branch>
ARG OAS_REF=0a4d614f9494cbadaba4a6fa32a33d6e54e14f34
RUN pip install --no-cache-dir "openaerostruct @ git+https://github.com/mdolab/OpenAeroStruct.git@${OAS_REF}"

# Copy SDK first (changes less often -> better layer caching)
COPY packages/sdk/ packages/sdk/
RUN pip install --no-cache-dir "packages/sdk[all]"

# Copy and install the OAS package (openaerostruct dep already satisfied)
COPY packages/oas/ packages/oas/
RUN pip install --no-cache-dir --no-deps packages/oas

# Create non-root user for runtime with a writable home directory
RUN useradd -r -m -s /usr/sbin/nologin oas && \
    mkdir -p /data && chown oas:oas /data

# Artifact storage root inside the container (bind-mounted from host)
ENV HANGAR_DATA_DIR=/data

# Matplotlib cache dir — avoids "Permission denied" warnings
ENV MPLCONFIGDIR=/tmp/matplotlib

# Default transport — override with OAS_TRANSPORT=http for streamable HTTP
ENV OAS_TRANSPORT=stdio

VOLUME /data

EXPOSE 8000

USER oas

CMD ["python", "-m", "hangar.oas.server"]
