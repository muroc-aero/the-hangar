FROM python:3.11-slim

# System dependencies for numpy (BLAS/LAPACK) and git (upstream fetch).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        gfortran \
        git \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install evtolpy from upstream. evtolpy ships no packaging metadata, so the
# managed patch adds a pyproject.toml before install. Remove this block once
# upstream packages itself. Default tracks scripts/upstream-pins.env (EVTOL_REF);
# bump both together. Shallow-fetch of an explicit ref so the default can be a
# commit SHA (git clone -b only accepts branch/tag names).
ARG EVTOL_REF=63d86971300485bad1ee6dbfc3ab9a85ee7c4ce4
RUN git init /tmp/evtolpy && \
    git -C /tmp/evtolpy fetch --depth 1 https://github.com/starbelt/evtolpy.git ${EVTOL_REF} && \
    git -C /tmp/evtolpy checkout FETCH_HEAD
COPY scripts/evtolpy-packaging.patch /tmp/evtolpy-packaging.patch
RUN cd /tmp/evtolpy && \
    git apply /tmp/evtolpy-packaging.patch || echo "Patch already applied or upstream packaged" && \
    pip install --no-cache-dir /tmp/evtolpy && \
    rm -rf /tmp/evtolpy /tmp/evtolpy-packaging.patch

# Copy SDK first (changes less often -> better layer caching)
COPY packages/sdk/ packages/sdk/
RUN pip install --no-cache-dir "packages/sdk[all]"

# Copy and install the evtol package (evtolpy dep already satisfied)
COPY packages/evtol/ packages/evtol/
RUN pip install --no-cache-dir --no-deps packages/evtol

# Create non-root user for runtime with a writable home directory
RUN useradd -r -m -s /usr/sbin/nologin evtol && \
    mkdir -p /data && chown evtol:evtol /data

ENV HANGAR_DATA_DIR=/data
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV EVTOL_TRANSPORT=stdio

VOLUME /data
EXPOSE 8000
USER evtol

CMD ["python", "-m", "hangar.evtol.server"]
