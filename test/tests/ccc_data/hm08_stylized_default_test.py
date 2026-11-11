"""tools/hm08/make_stylized_default.py must reproduce the committed stylized-default target byte for byte."""
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(REPO, "tools", "hm08", "make_stylized_default.py")
TARGET = os.path.join(REPO, "tools", "hm08", "stylized-default.target.gz")


def _python_with_scipy():
    import shutil
    for exe in (sys.executable, shutil.which("python3")):
        if exe and subprocess.run([exe, "-c", "import numpy, scipy"], capture_output=True).returncode == 0:
            return exe
    return None


def test_stylized_default_target_reproduces():
    exe = _python_with_scipy()
    assert exe, "need a python with numpy and scipy to run make_stylized_default.py"
    with open(TARGET, "rb") as f:
        committed = f.read()
    try:
        # The script writes its output in place; compare, then restore.
        run = subprocess.run([exe, "-I", SCRIPT], capture_output=True, text=True, cwd=REPO)
        assert run.returncode == 0, run.stderr
        with open(TARGET, "rb") as f:
            assert f.read() == committed
    finally:
        with open(TARGET, "wb") as f:
            f.write(committed)
