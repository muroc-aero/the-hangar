FROM python:3.11-slim

# System dependencies for numpy/scipy (BLAS/LAPACK) and compiled extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        gfortran \
        git \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Aviary from upstream at a pinned ref (brings openmdao>=3.43,
# dymos, numpy 2 -- this image is the isolated Aviary environment; no
# openconcept/oas/pycycle here, so the workspace numpy-2 conflict does not
# apply). Default tracks scripts/upstream-pins.env (AVY_REF); bump both
# together. Override at build time: --build-arg AVY_REF=<commit|tag|branch>
ARG AVY_REF=2af552a9b2aae5965c12ae8afde091cce7587c32
RUN pip install --no-cache-dir "aviary @ git+https://github.com/OpenMDAO/Aviary.git@${AVY_REF}"

# OpenAeroStruct + ambiance for the OAS-in-Aviary external subsystem
# (aviary's own numpy-2 stack satisfies OAS -- no cap conflict here).
# Default tracks OAS_REF in scripts/upstream-pins.env; bump both together.
ARG OAS_REF=0a4d614f9494cbadaba4a6fa32a33d6e54e14f34
RUN pip install --no-cache-dir \
        "openaerostruct @ git+https://github.com/mdolab/OpenAeroStruct.git@${OAS_REF}" \
        ambiance

# Copy SDK first (changes less often -> better layer caching)
COPY packages/sdk/ packages/sdk/
RUN pip install --no-cache-dir "packages/sdk[all]"

# Copy and install the avy package (aviary dep already satisfied)
COPY packages/avy/ packages/avy/
RUN pip install --no-cache-dir --no-deps packages/avy

# Create non-root user for runtime with a writable home directory
RUN useradd -r -m -s /usr/sbin/nologin avy && \
    mkdir -p /data && chown avy:avy /data

ENV HANGAR_DATA_DIR=/data
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV AVY_TRANSPORT=stdio

VOLUME /data
EXPOSE 8000
USER avy

CMD ["python", "-m", "hangar.avy.server"]
