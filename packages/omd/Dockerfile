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

# results-reader (read seam for the analysis DB)
COPY packages/results-reader/ packages/results-reader/
RUN pip install --no-cache-dir packages/results-reader

# hangar-evt: the native evt/Sizing and evt/Mission factories live in
# hangar.omd.evt but read the pure-data config schema from
# hangar.evt.config.defaults, so the package must be importable. Installed
# WITHOUT deps on purpose -- the native path needs no evtolpy upstream lib.
# (evt/SizingFD, the black-box fallback, does; it errors with a clear message
# if invoked here.)
COPY packages/evt/ packages/evt/
RUN pip install --no-cache-dir --no-deps packages/evt

# Copy and install the omd package (openaerostruct dep already satisfied;
# ocp/pyc factories degrade gracefully when those extras are absent)
COPY packages/omd/ packages/omd/
RUN pip install --no-cache-dir --no-deps packages/omd && \
    pip install --no-cache-dir click jsonschema pyyaml matplotlib "openmdao>=3.35,!=3.40"

# Aviary runtime for the avy/Sizing factory. Aviary needs numpy>=2 while
# this image's OAS/openconcept stack is numpy<2, so -- exactly as in dev
# (.venv-avy, scripts/setup-avy-venv.sh) -- it lives in its own venv and
# the factory runs it as a subprocess (factories/avy_worker.py). Same
# contents and pins as packages/avy/Dockerfile: aviary at AVY_REF,
# openaerostruct + ambiance for the oas_wing_mass subsystem, hangar-sdk,
# hangar-avy. AVY_PYTHON is what the factory resolves the interpreter from.
ARG AVY_REF=2af552a9b2aae5965c12ae8afde091cce7587c32
COPY packages/avy/ packages/avy/
RUN python -m venv /opt/venv-avy && \
    /opt/venv-avy/bin/pip install --no-cache-dir \
        "aviary @ git+https://github.com/OpenMDAO/Aviary.git@${AVY_REF}" \
        "openaerostruct @ git+https://github.com/mdolab/OpenAeroStruct.git@${OAS_REF}" \
        ambiance && \
    /opt/venv-avy/bin/pip install --no-cache-dir "packages/sdk[all]" && \
    /opt/venv-avy/bin/pip install --no-cache-dir --no-deps packages/avy
ENV AVY_PYTHON=/opt/venv-avy/bin/python

# Create non-root user for runtime with a writable home directory
RUN useradd -r -m -s /usr/sbin/nologin omd && \
    mkdir -p /data && chown omd:omd /data

# Artifact storage root inside the container (bind-mounted from host)
ENV HANGAR_DATA_DIR=/data

# Matplotlib cache dir — avoids "Permission denied" warnings
ENV MPLCONFIGDIR=/tmp/matplotlib

# Default transport — override with OMD_TRANSPORT=http for streamable HTTP
ENV OMD_TRANSPORT=stdio

VOLUME /data

EXPOSE 8000

USER omd

CMD ["python", "-m", "hangar.omd.server"]
