"""
Environment audit for the market-analysis-bot project.

Run:  python audit_environment.py

Read-only: installs nothing, modifies nothing, never prints secrets.
Stdlib only, so it works before any pip packages are installed.
Output is also saved to audit_report.txt so you can paste it back.
"""

from __future__ import annotations

import glob
import json
import platform
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from urllib.request import urlopen

OK, BAD, WARN = "OK", "MISSING", "WARN"

results: dict[str, tuple[str, str]] = {}
order: list[str] = []


def add(label: str, status: str, detail: str = "") -> None:
    results[label] = (status, detail)
    order.append(label)


def try_pkg(name: str) -> str | None:
    try:
        return pkg_version(name)
    except PackageNotFoundError:
        return None


def check_python() -> None:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 9)
    add("Python", OK if ok else BAD,
        f"{v.major}.{v.minor}.{v.micro} ({platform.architecture()[0]})")
    if not ok:
        add("Python hint", WARN, "3.9+ required, 3.11+ recommended (64-bit)")
    elif platform.architecture()[0] != "64bit":
        add("Python hint", WARN, "MetaTrader5 package requires 64-bit Python")


def check_pip() -> None:
    try:
        out = subprocess.run([sys.executable, "-m", "pip", "--version"],
                             capture_output=True, text=True, timeout=30)
        first = (out.stdout or out.stderr).strip().splitlines()
        add("pip", OK, first[0] if first else "")
    except Exception as exc:
        add("pip", BAD, repr(exc))


def check_python_packages(mt5_pkg: str | None) -> None:
    add("Python MT5 package", OK if mt5_pkg else BAD,
        mt5_pkg or "run: pip install MetaTrader5  (Windows + 64-bit Python only)")
    for name in ["pandas", "numpy", "python-dotenv", "requests", "pytest"]:
        ver = try_pkg(name)
        add(f"pkg: {name}", OK if ver else BAD, ver or "not installed")


def find_mt5_install() -> str:
    for c in (r"C:\Program Files\MetaTrader 5\terminal64.exe",
              r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe"):
        if Path(c).exists():
            return c
    hits = glob.glob(r"C:\Program Files*\*\terminal64.exe")
    return hits[0] if hits else ""


def check_mt5_terminal() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "non-Windows platform"
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/NH"],
            capture_output=True, text=True, timeout=30).stdout.lower()
        if "terminal64.exe" in out:
            return True, "terminal64.exe is running"
        return False, "terminal64.exe is not running"
    except Exception as exc:
        return False, f"could not query processes: {exc}"


def check_ollama() -> None:
    host = "http://localhost:11434"
    try:
        with urlopen(f"{host}/api/tags", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "?") for m in data.get("models", [])][:5]
        add("Ollama", OK, host + (" | models: " + ", ".join(names) if names
                                  else " | no models pulled"))
    except Exception:
        add("Ollama", WARN, "not running (optional; core bot works without it)")


def check_telegram() -> None:
    env_path = Path(".env")
    token = chat_id = ""
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
            elif line.startswith("TELEGRAM_CHAT_ID="):
                chat_id = line.split("=", 1)[1].strip()
    if token and chat_id:
        add("Telegram", OK, "configured in .env (values never printed)")
    elif env_path.exists():
        add("Telegram", WARN, ".env found but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID incomplete")
    else:
        add("Telegram", WARN, "not configured (needed from Phase 9 onward)")


def check_git() -> None:
    path = shutil.which("git")
    if not path:
        add("Git", WARN, "not found (optional, recommended)")
        return
    try:
        ver = subprocess.run(["git", "--version"], capture_output=True,
                             text=True, timeout=15).stdout.strip()
    except Exception:
        ver = ""
    add("Git", OK, ver or path)


def check_vscode() -> None:
    code = shutil.which("code")
    add("VS Code CLI", OK if code else WARN,
        code or "'code' not on PATH (IDE itself may still be installed)")
    has_ws = Path(".vscode").is_dir()
    add("VS Code workspace", OK if has_ws else WARN,
        ".vscode/ present" if has_ws else "no .vscode folder in this directory")


def check_existing_project() -> None:
    expected = ["main.py", "config.py", "requirements.txt", ".env.example",
                "data/mt5_client.py", "analysis/analyzer.py",
                "telegram_bot/bot.py", "storage/database.py"]
    found = [f for f in expected if Path(f).exists()]
    add("Existing project files", OK if found else WARN,
        ", ".join(found) if found else "none found - clean start")


def recommended_next_step(mt5_pkg: str | None, running: bool, install_path: str) -> str:
    if (sys.version_info.major, sys.version_info.minor) < (3, 9):
        return ("Install Python 3.11+ (64-bit) from python.org "
                "(tick 'Add python.exe to PATH'), then re-run this audit.")
    if mt5_pkg is None:
        return ("Run:  pip install MetaTrader5 pandas python-dotenv   "
                "then re-run this audit.")
    if not running:
        hint = "Start MetaTrader 5 and log in to your broker account."
        if install_path:
            hint += f" (terminal found at: {install_path})"
        return hint + "  Then run:  python main.py --symbol EURUSD --timeframe M5 --count 20"
    return ("All prerequisites present. Run the Phase 2 milestone:  "
            "python main.py --symbol EURUSD --timeframe M5 --count 20")


def main() -> None:
    check_python()
    check_pip()
    mt5_pkg = try_pkg("MetaTrader5")
    check_python_packages(mt5_pkg)

    running, run_detail = check_mt5_terminal()
    install_path = find_mt5_install()
    add("MetaTrader 5 terminal", OK if running else BAD, run_detail)
    add("MetaTrader 5 install path", OK if install_path else WARN,
        install_path or "not found in default locations (broker-specific folders are common)")

    check_git()
    check_vscode()
    check_ollama()
    check_telegram()
    check_existing_project()

    lines = [f"{label}: {results[label][0]}" +
             (f" | {results[label][1]}" if results[label][1] else "")
             for label in order]

    print()
    print("ENVIRONMENT AUDIT")
    print("=" * 70)
    for line in lines:
        print(line)
    print("=" * 70)
    step = recommended_next_step(mt5_pkg, running, install_path)
    print(f"Recommended next step:\n  {step}")

    Path("audit_report.txt").write_text(
        "\n".join(lines) + f"\n\nRecommended next step:\n  {step}\n",
        encoding="utf-8")
    print("\n(Saved to audit_report.txt)")


if __name__ == "__main__":
    main()