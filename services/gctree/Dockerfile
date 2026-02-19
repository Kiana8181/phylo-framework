# services/gctree/Dockerfile
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/usr/lib/python3/dist-packages \
    QT_QPA_PLATFORM=offscreen \
    MPLBACKEND=agg \
    XDG_RUNTIME_DIR=/tmp/runtime-gctree \
    CONTRACTS_DIR=/contracts

# System deps: PHYLIP provides dnapars; plus fonts for matplotlib SVG.
RUN apt-get update -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 \
    phylip ca-certificates curl tini fonts-dejavu-core \
    python3-pyqt5 python3-pyqt5.qtsvg python3-pyqt5.qtopengl libqt5svg5 libqt5opengl5 libgl1 libxcb-xinerama0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt ./requirements.txt
RUN grep -vE '^[[:space:]]*PyQt5([<>=!~].*)?$' requirements.txt > /tmp/requirements.docker.txt \
    && pip install -r /tmp/requirements.docker.txt

COPY sitecustomize.py /tmp/sitecustomize.py
RUN python - <<'PY'
import pathlib
import shutil
import site

dst = pathlib.Path(site.getsitepackages()[0]) / "sitecustomize.py"
shutil.copyfile("/tmp/sitecustomize.py", dst)
print(f"Installed {dst}")
PY

# Build-time regression smoke test for ETE rendering under PyQt5.
# This catches:
# - ModuleNotFoundError: No module named 'PyQt5.QtSvg'
# - AttributeError: module 'ete3' has no attribute 'NodeStyle'
RUN python - <<'PY'
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
rt = Path("/tmp/runtime-gctree")
rt.mkdir(parents=True, exist_ok=True)
try:
    rt.chmod(0o700)
except Exception:
    pass
os.environ.setdefault("XDG_RUNTIME_DIR", str(rt))

from PyQt5 import QtOpenGL  # noqa: F401
from PyQt5 import QtSvg  # noqa: F401
import ete3

if not hasattr(ete3, "NodeStyle"):
    raise RuntimeError("ETE smoke test failed: ete3.NodeStyle is unavailable")

t = ete3.Tree("(A:1,B:1);")
for n in t.traverse():
    nstyle = ete3.NodeStyle()
    nstyle["size"] = 0
    n.set_style(nstyle)

out = Path(tempfile.mkdtemp(prefix="ete_smoke_")) / "smoke.svg"
t.render(str(out))
if not out.exists() or out.stat().st_size <= 0:
    raise RuntimeError("ETE smoke test failed: render output not created")
print(f"ETE smoke render OK: {out}")
PY
COPY app.py /srv/app.py

EXPOSE 8002
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8002"]
