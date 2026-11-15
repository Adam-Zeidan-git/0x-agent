import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_case_flag_runs(tmp_path):
    out = subprocess.run([sys.executable, "-m", "autoclose", "--case", str(ROOT / "samples" / "cafe_beirut"),
                          "--no-nim", "--data", str(tmp_path)], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert "STOCK REVIEW" in out.stdout


def test_case_flag_bad_folder(tmp_path):
    out = subprocess.run([sys.executable, "-m", "autoclose", "--case", str(tmp_path / "nope")],
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 2
