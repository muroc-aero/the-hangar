FROM python:3.11-slim

# System dependencies for numpy/scipy (BLAS/LAPACK) and compiled extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        gfortran \
        git \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install OpenConcept from upstream at a pinned ref.
# Default tracks scripts/upstream-pins.env (OCP_REF); bump both together.
# Override at build time: --build-arg OCP_REF=<commit|tag|branch>
ARG OCP_REF=0d2adeb6f6855b3cbe77b1c1453c5cf22c7fe5ca
RUN pip install --no-cache-dir "openconcept @ git+https://github.com/mdolab/openconcept.git@${OCP_REF}"

# Copy SDK first (changes less often -> better layer caching)
COPY packages/sdk/ packages/sdk/
RUN pip install --no-cache-dir "packages/sdk[all]"

# Copy and install the OCP package (openconcept dep already satisfied)
COPY packages/ocp/ packages/ocp/
RUN pip install --no-cache-dir --no-deps packages/ocp

# Create non-root user for runtime with a writable home directory
RUN useradd -r -m -s /usr/sbin/nologin ocp && \
    mkdir -p /data && chown ocp:ocp /data

ENV HANGAR_DATA_DIR=/data
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV OCP_TRANSPORT=stdio

VOLUME /data
EXPOSE 8000
USER ocp

CMD ["python", "-m", "hangar.ocp.server"]
