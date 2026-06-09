FROM python:3.11-slim

# System dependencies for numpy/scipy (BLAS/LAPACK) and compiled extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        gfortran \
        git \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pyCycle from upstream with numpy 2.x compatibility patch.
# The patch fixes np.complex removal and shape-(1,) scalar assignment.
# Remove this block once upstream merges OpenMDAO/pyCycle#116.
# Default tracks scripts/upstream-pins.env (PYC_REF); bump both together.
# Shallow-fetch of an explicit ref so the default can be a commit SHA
# (git clone -b only accepts branch/tag names).
ARG PYC_REF=d1dda5ffe200c88336a64ffd13b6c59b5f63343b
RUN git init /tmp/pyCycle && \
    git -C /tmp/pyCycle fetch --depth 1 https://github.com/OpenMDAO/pyCycle.git ${PYC_REF} && \
    git -C /tmp/pyCycle checkout FETCH_HEAD
COPY scripts/pycycle-numpy2.patch /tmp/pycycle-numpy2.patch
RUN cd /tmp/pyCycle && \
    git apply /tmp/pycycle-numpy2.patch || echo "Patch already applied or upstream fixed" && \
    pip install --no-cache-dir /tmp/pyCycle && \
    rm -rf /tmp/pyCycle /tmp/pycycle-numpy2.patch

# Copy SDK first (changes less often -> better layer caching)
COPY packages/sdk/ packages/sdk/
RUN pip install --no-cache-dir "packages/sdk[all]"

# Copy and install the PYC package (om-pycycle dep already satisfied)
COPY packages/pyc/ packages/pyc/
RUN pip install --no-cache-dir --no-deps packages/pyc

# Create non-root user for runtime with a writable home directory
RUN useradd -r -m -s /usr/sbin/nologin pyc && \
    mkdir -p /data && chown pyc:pyc /data

ENV HANGAR_DATA_DIR=/data
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV PYC_TRANSPORT=stdio

VOLUME /data
EXPOSE 8000
USER pyc

CMD ["python", "-m", "hangar.pyc.server"]
