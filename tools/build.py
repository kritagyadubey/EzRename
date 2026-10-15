"""Build the EzRename executables and smoke-test them.

    python tools/build.py            # build + test
    python tools/build.py --no-test  # build only

The script is the reproducible definition of a release: it regenerates the
icon, runs PyInstaller against ``packaging/ezrename.spec``, then executes both
packaged binaries from their final ``dist`` location against disposable folders
and reports the real exit codes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
GUI_EXE = DIST / "EzRename" / "EzRename.exe"
CLI_EXE = DIST / "ezrename-cli" / "ezrename-cli.exe"


def run(label: str, command: list[str], *, cwd: Path | None = None, timeout: int = 300) -> tuple[int, str]:
    print(f"\n$ {' '.join(str(part) for part in command)}")
    result = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    output = (result.stdout or "") + (result.stderr or "")
    print(output.strip()[:4000])
    print(f"[{label}] exit code {result.returncode}")
    return result.returncode, output


def build() -> int:
    icon = ROOT / "assets" / "ezrename.ico"
    if not icon.exists():
        run("icons", [sys.executable, str(ROOT / "tools" / "make_icons.py")])

    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)
    code, _ = run(
        "pyinstaller",
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "packaging/ezrename.spec",
            "--noconfirm",
            "--clean",
            "--log-level",
            "WARN",
        ],
        timeout=1800,
    )
    if code != 0:
        return code
    for target in (GUI_EXE, CLI_EXE):
        if not target.exists():
            print(f"missing build output: {target}")
            return 1
        print(f"built {target} ({target.stat().st_size // 1024} KB)")
    return 0


def smoke_test() -> int:
    """Run both packaged executables the way a user would."""

    failures: list[str] = []
    home = Path(tempfile.mkdtemp(prefix="ezrename-release-home-"))
    env_home = ["--home", str(home)]

    def check(label: str, condition: bool, detail: str = "") -> None:
        print(f"  {'ok ' if condition else 'FAIL'} {label}{(' - ' + detail) if detail and not condition else ''}")
        if not condition:
            failures.append(label)

    print("\n=== packaged CLI ===")
    code, output = run("cli --version", [CLI_EXE, "--version"], timeout=120)
    check("cli --version exits 0", code == 0, output)
    check("cli --version prints the version", "1.0.0" in output, output)

    code, output = run("cli --help", [CLI_EXE, "--help"], timeout=120)
    check("cli --help exits 0", code == 0, output)
    check("cli --help documents rename", "rename" in output and "undo" in output, output)

    work = Path(tempfile.mkdtemp(prefix="ezrename-release-work-"))
    for name in ("IMG_0001.jpg", "IMG_0002.jpg", "report FINAL.pdf"):
        (work / name).write_text("release test", encoding="utf-8")

    code, output = run("cli list", [CLI_EXE, *env_home, "list", str(work), "--no-color"], timeout=120)
    check("cli list exits 0", code == 0, output)
    check("cli list shows the files", "IMG_0001.jpg" in output, output)

    code, output = run(
        "cli preview --json",
        [CLI_EXE, *env_home, "preview", str(work), "--prefix", "Vacation_", "--json"],
        timeout=120,
    )
    check("cli preview --json exits 0", code == 0, output)
    try:
        payload = json.loads(output[output.index("{") :])
        check("cli preview --json is valid JSON", payload["summary"]["rename"] == 3, output)
    except (ValueError, KeyError):
        check("cli preview --json is valid JSON", False, output)

    code, output = run(
        "cli rename --dry-run",
        [CLI_EXE, *env_home, "rename", str(work), "--case", "lower", "--dry-run", "--no-color"],
        timeout=120,
    )
    check("cli dry run exits 0", code == 0, output)
    check("cli dry run changed nothing", (work / "IMG_0001.jpg").exists(), "")

    code, output = run(
        "cli rename --yes",
        [
            CLI_EXE,
            *env_home,
            "rename",
            str(work),
            "--find",
            "IMG_",
            "--replace",
            "Photo_",
            "--yes",
            "--no-color",
        ],
        timeout=120,
    )
    check("cli rename exits 0", code == 0, output)
    check("cli rename renamed the files", (work / "Photo_0001.jpg").exists(), output)

    code, output = run("cli history", [CLI_EXE, *env_home, "history", "--json"], timeout=120)
    check("cli history exits 0", code == 0, output)
    check("cli history recorded the session", "renamed" in output, output)

    code, output = run("cli undo --yes", [CLI_EXE, *env_home, "undo", "--last", "--yes", "--no-color"], timeout=120)
    check("cli undo exits 0", code == 0, output)
    check("cli undo restored the name", (work / "IMG_0001.jpg").exists(), output)

    code, output = run("cli usage error", [CLI_EXE, *env_home, "rename", "--nonsense"], timeout=120)
    check("cli invalid option exits 2", code == 2, output)

    code, output = run("cli missing path", [CLI_EXE, *env_home, "list", str(work / "nope")], timeout=120)
    check("cli missing folder exits 2", code == 2, output)

    print("\n=== packaged GUI ===")
    code, output = run("gui --version", [GUI_EXE, "--version"], timeout=120)
    check("gui --version exits 0", code == 0, output)

    code, output = run("gui --self-test", [GUI_EXE, "--self-test"], timeout=240)
    check("gui --self-test exits 0", code == 0, output)
    check("gui self test built the interface", "successfully" in output, output)

    # Launch the real window and make sure it survives a few seconds.
    print("\n$ EzRename.exe  (launch check)")
    process = subprocess.Popen(
        [str(GUI_EXE)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "EZRENAME_HOME": str(home)},
    )
    time.sleep(6)
    alive = process.poll() is None
    check("gui stays running when launched normally", alive, f"exited with {process.returncode}")
    if alive:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()

    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)

    print("\n=== summary ===")
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("all packaged checks passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and test the EzRename executables")
    parser.add_argument("--no-test", action="store_true", help="build without the smoke tests")
    parser.add_argument("--only-test", action="store_true", help="test an existing build")
    args = parser.parse_args()

    if not args.only_test:
        code = build()
        if code != 0:
            print("build failed")
            return code
    if not args.no_test:
        return smoke_test()
    return 0


if __name__ == "__main__":
    sys.exit(main())
