"""Process-wide matplotlib render lock and atomic file writes.

matplotlib's pyplot interface keeps a global figure manager, so two threads
rendering at the same time can mix figure state (wrong axes on the wrong
figure, closed-figure errors). In one server process this happens between
the SDK ``/plot`` endpoint, the omd ``/omd-plots`` on-demand generation, the
``generate_plots`` / ``get_run_summary`` MCP tools, and the autostarted
range-safety dashboard. Every hangar module that renders through pyplot must
hold :data:`MPL_RENDER_LOCK` from figure creation through ``savefig`` and
``close``.

Writers also share output paths (the dashboard and the MCP tools both write
``plots/{run_id}/{type}.png``), so PNGs/HTML are written via a temp file in
the same directory + ``os.replace`` — concurrent readers never see a torn
file.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

# Reentrant so a locked plot function may call locked helpers.
MPL_RENDER_LOCK = threading.RLock()


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Write *data* to *path* atomically (temp file + ``os.replace``)."""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_savefig(fig, path: str | Path, **savefig_kwargs) -> None:
    """Save a matplotlib figure to *path* atomically.

    Renders to a temp file in the destination directory, then
    ``os.replace``s it over *path*. The caller is responsible for holding
    :data:`MPL_RENDER_LOCK` (savefig touches global matplotlib state).
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".png")
    os.close(fd)
    try:
        fig.savefig(tmp_name, **savefig_kwargs)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
