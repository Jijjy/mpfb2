"""tools/hm08/make_stylized_default.py must reproduce the committed stylized-default and stylized-chunky targets
byte for byte, and the shipped copies under data/targets/stylization must be those files."""
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(REPO, "tools", "hm08", "make_stylized_default.py")
NAMES = ("stylized-default", "stylized-chunky")
TARGETS = [os.path.join(REPO, "tools", "hm08", name + ".target.gz") for name in NAMES]
SHIPPED = [os.path.join(REPO, "src", "mpfb", "data", "targets", "stylization", name + ".target.gz") for name in NAMES]


def _python_with_scipy():
    import shutil
    for exe in (sys.executable, shutil.which("python3")):
        if exe and subprocess.run([exe, "-c", "import numpy, scipy"], capture_output=True).returncode == 0:
            return exe
    return None


def test_stylized_default_target_reproduces():
    exe = _python_with_scipy()
    assert exe, "need a python with numpy and scipy to run make_stylized_default.py"
    committed = []
    for path in TARGETS:
        with open(path, "rb") as f:
            committed.append(f.read())
    for path, data in zip(SHIPPED, committed):
        with open(path, "rb") as f:
            assert f.read() == data, path + " differs from the tools/hm08 copy"
    try:
        # The script writes its output in place; compare, then restore.
        run = subprocess.run([exe, "-I", SCRIPT], capture_output=True, text=True, cwd=REPO)
        assert run.returncode == 0, run.stderr
        for path, data in zip(TARGETS, committed):
            with open(path, "rb") as f:
                assert f.read() == data, path
    finally:
        for path, data in zip(TARGETS, committed):
            with open(path, "wb") as f:
                f.write(data)
