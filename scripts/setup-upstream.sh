#!/bin/bash
# Clone upstream engineering tool repos for local reference
# These are .gitignore'd — not part of the hangar repo

set -e
UPSTREAM_DIR="$(dirname "$0")/../upstream"
mkdir -p "$UPSTREAM_DIR"

echo "Cloning OpenAeroStruct..."
if [ ! -d "$UPSTREAM_DIR/OpenAeroStruct" ]; then
    git clone https://github.com/mdolab/OpenAeroStruct "$UPSTREAM_DIR/OpenAeroStruct"
else
    # git -C "$UPSTREAM_DIR/OpenAeroStruct" pull origin <branch-name>
    echo "  Already exists, pulling latest..."
    git -C "$UPSTREAM_DIR/OpenAeroStruct" pull
fi

echo "Cloning OpenConcept..."
if [ ! -d "$UPSTREAM_DIR/openconcept" ]; then
    git clone https://github.com/mdolab/openconcept "$UPSTREAM_DIR/openconcept"
else
    echo "  Already exists, pulling latest..."
    git -C "$UPSTREAM_DIR/openconcept" pull
fi

echo "Cloning pyCycle..."
if [ ! -d "$UPSTREAM_DIR/pyCycle" ]; then
    git clone https://github.com/OpenMDAO/pyCycle "$UPSTREAM_DIR/pyCycle"
else
    echo "  Already exists, pulling latest..."
    git -C "$UPSTREAM_DIR/pyCycle" pull
fi

# Apply numpy 2.x compatibility patch (fixes np.complex removal and
# shape-(1,) scalar assignment).  Tracks upstream issue OpenMDAO/pyCycle#116.
# Remove this block once the upstream PR is merged.
PYCYCLE_PATCH="$(dirname "$0")/pycycle-numpy2.patch"
if [ -f "$PYCYCLE_PATCH" ]; then
    echo "  Applying numpy 2.x compat patch..."
    git -C "$UPSTREAM_DIR/pyCycle" apply --check "$PYCYCLE_PATCH" 2>/dev/null \
        && git -C "$UPSTREAM_DIR/pyCycle" apply "$PYCYCLE_PATCH" \
        || echo "  Patch already applied or upstream fixed — skipping."
fi

echo "Cloning OpenMDAO..."
if [ ! -d "$UPSTREAM_DIR/OpenMDAO" ]; then
    git clone https://github.com/OpenMDAO/OpenMDAO "$UPSTREAM_DIR/OpenMDAO"
else
    echo "  Already exists, pulling latest..."
    git -C "$UPSTREAM_DIR/OpenMDAO" pull
fi

echo "Cloning AeroSandbox..."
if [ ! -d "$UPSTREAM_DIR/AeroSandbox" ]; then
    git clone https://github.com/peterdsharpe/AeroSandbox "$UPSTREAM_DIR/AeroSandbox"
else
    echo "  Already exists, pulling latest..."
    git -C "$UPSTREAM_DIR/AeroSandbox" pull
fi

echo "Done. Upstream repos are in upstream/ (git-ignored)."
echo "To use editable installs, uncomment the [tool.uv.sources] line in packages/oas/pyproject.toml"
