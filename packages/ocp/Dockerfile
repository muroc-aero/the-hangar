FROM python:3.11-slim

# System dependencies for numpy/scipy (BLAS/LAPACK) and compiled extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        gfortran \
        git \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install OpenConcept from upstream at a pinned ref, with the managed numpy-2
# patch applied (scripts/openconcept-numpy2.patch -- the same one
# scripts/setup-upstream.sh applies to the dev clone; it also lifts the
# numpy<2 metadata pin). Default tracks scripts/upstream-pins.env (OCP_REF);
# bump both together. Override at build time: --build-arg OCP_REF=<commit>
ARG OCP_REF=0d2adeb6f6855b3cbe77b1c1453c5cf22c7fe5ca
COPY scripts/openconcept-numpy2.patch /tmp/openconcept-numpy2.patch
RUN git clone --quiet https://github.com/mdolab/openconcept.git /tmp/openconcept && \
    git -C /tmp/openconcept checkout --quiet "${OCP_REF}" && \
    git -C /tmp/openconcept apply /tmp/openconcept-numpy2.patch && \
    pip install --no-cache-dir "numpy>=2,<2.4" "openmdao>=3.43" /tmp/openconcept && \
    rm -rf /tmp/openconcept /tmp/openconcept-numpy2.patch

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
