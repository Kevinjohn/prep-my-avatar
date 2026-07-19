"""LoRA Dataset Studio - portable launcher.

Double-clicked by end users. Starts the bundled standalone Python running the Flask
server (no console window), waits until it answers, opens the browser, and shows a
tiny status window with Open / Quit. Everything writable (config.json, .env, the
datasets) lives under data/ next to this launcher, so the bundle stays fully portable.

Frozen with PyInstaller (--noconsole) into "LoRA Dataset Studio.exe" at the bundle root.
The APP runs under python/python.exe, which HAS pip -- that is the whole reason we ship
a real standalone Python instead of one frozen single-exe: the in-app Setup wizard's
`pip install -r backend/requirements-ml.txt` (face scoring, masks) keeps working.

Bundle layout the launcher expects (mirrors the repo so backend/config.py's
REPO_ROOT/FRONTEND_DIST resolve unchanged):

    LoRA Dataset Studio.exe   <- this, frozen
    python/python.exe         <- standalone CPython + core deps (has pip)
    backend/run.py            <- Flask entrypoint
    frontend/dist/            <- prebuilt UI
    data/                     <- created on first run (config.json, .env, datasets)
"""
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "LoRA Dataset Studio"
PREFERRED_PORT = 5050          # matches start.bat; only changed if already taken
CREATE_NO_WINDOW = 0x08000000  # Windows: no console window for the child server
RESTART_EXIT_CODE = 75


def bundle_dir() -> Path:
    """Frozen: the exe sits at the bundle root. Dev (python packaging/launcher.py):
    the repo root is one level up from packaging/."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0   # nothing listening -> free


def pick_port() -> int:
    """Prefer 5050; if it's taken (another Flask app, a previous instance), let the OS
    hand out a free one so two people double-clicking never collide."""
    if _port_free(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def python_exe(bundle: Path) -> Path:
    """The bundled standalone interpreter (python/python.exe on Windows; python/bin/python
    elsewhere, so the launcher can also be smoke-tested on a dev machine)."""
    win = bundle / "python" / "python.exe"
    return win if win.exists() else bundle / "python" / "bin" / "python"


def run_recovery_bootstrap(bundle: Path) -> tuple[bool, str]:
    """Run the pre-update recovery copy before importing checkout code."""
    recovery = bundle / "data" / "update-recovery.py"
    if not recovery.is_file():
        return True, ""
    result = subprocess.run(
        [str(python_exe(bundle)), str(recovery), "--root", str(bundle),
         "--data-dir", str(bundle / "data")],
        cwd=str(bundle), capture_output=True, text=True, timeout=1200,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    detail = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, detail


def start_server(bundle: Path, host: str, port: int) -> subprocess.Popen:
    data = bundle / "data"
    data.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # Keep every writable file under data/ so the bundle is portable (nothing written
    # next to the code, nothing in %APPDATA%). These overrides are read by config.py.
    env["LDS_CONFIG"] = str(data / "config.json")
    env["LDS_DATA_DIR"] = str(data)
    env["LDS_ENV"] = str(data / ".env")
    env["LDS_HOST"] = host
    env["LDS_PORT"] = str(port)
    env["LDS_LAUNCHER_SUPERVISED"] = "1"
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    log = open(data / "server.log", "ab", buffering=0)   # keep the server's own diagnostics
    try:
        return subprocess.Popen(
            [str(python_exe(bundle)), str(bundle / "backend" / "run.py")],
            cwd=str(bundle), env=env, stdout=log, stderr=log, creationflags=flags,
        )
    finally:
        log.close()


def _consume_restart_request(bundle: Path, host: str, port: int) -> tuple[str, int]:
    """Read the child's durable restart hand-off, then remove it atomically enough
    for a single launcher. Invalid or partial files never alter the current bind."""
    path = bundle / "data" / "restart-request.json"
    try:
        import json
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidate_host = str(payload.get("host") or "").strip()
        candidate_port = int(payload.get("port"))
        if not candidate_host or len(candidate_host) > 255 or "\x00" in candidate_host:
            raise ValueError("invalid host")
        if not 1 <= candidate_port <= 65535:
            raise ValueError("invalid port")
        return candidate_host, candidate_port
    except (OSError, ValueError, TypeError):
        return host, port
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def _browser_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    return f"http://{browser_host}:{port}/"


def wait_until_up(health_url: str, proc: subprocess.Popen, timeout: float = 90.0) -> bool:
    """Poll /api/health until 200, or the server process dies, or we time out. First
    launch can be slow (SQLite init + additive migrations), hence the generous window."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:      # server exited during startup -> give up
            return False
        try:
            with urllib.request.urlopen(health_url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def report_startup_result(up: bool, proc: subprocess.Popen, url: str,
                          update_ui, opened: bool) -> bool:
    """Surface readiness before the supervisor blocks waiting for process exit."""
    if up:
        update_ui(f"✅ Running\n{url}", enabled=True, open_browser=not opened)
        return True
    if proc.poll() is None:
        update_ui("⚠️ The server is running but did not become ready.\n"
                  "See data\\server.log for details.")
    return opened


def main() -> int:
    import tkinter as tk
    from tkinter import ttk

    bundle = bundle_dir()
    py = python_exe(bundle)
    if not py.exists():
        _fatal(f"Bundled Python not found at {py}.\nThe download may be incomplete — "
               "re-extract the .zip.")
        return 1
    recovered, recovery_detail = run_recovery_bootstrap(bundle)
    if not recovered:
        _fatal("An interrupted update could not be recovered safely.\n\n"
               + (recovery_detail or "See data\\server.log for details."))
        return 1

    state = {
        "host": "127.0.0.1",
        "port": pick_port(),
        "proc": None,
        "url": "",
    }
    state["url"] = _browser_url(state["host"], state["port"])
    stop = threading.Event()

    root = tk.Tk()
    root.title(APP_NAME)
    root.resizable(False, False)
    ico = bundle / "icon.ico"
    if ico.exists():
        try:
            root.iconbitmap(str(ico))
        except Exception:
            pass

    frame = ttk.Frame(root, padding=20)
    frame.grid()
    ttk.Label(frame, text="🧬 " + APP_NAME, font=("Segoe UI", 12, "bold")).grid(
        row=0, column=0, columnspan=2, pady=(0, 8))
    status = tk.StringVar(value="Starting the server…")
    ttk.Label(frame, textvariable=status, justify="center", font=("Segoe UI", 10)).grid(
        row=1, column=0, columnspan=2, pady=(0, 14))

    open_btn = ttk.Button(frame, text="Open", state="disabled",
                          command=lambda: webbrowser.open(state["url"]))
    open_btn.grid(row=2, column=0, padx=4, ipadx=10)

    def on_quit():
        stop.set()
        try:
            proc = state.get("proc")
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass
        root.destroy()

    ttk.Button(frame, text="Quit", command=on_quit).grid(row=2, column=1, padx=4, ipadx=10)
    root.protocol("WM_DELETE_WINDOW", on_quit)

    def update_ui(message, *, enabled=False, open_browser=False):
        def apply():
            status.set(message)
            open_btn.state(["!disabled"] if enabled else ["disabled"])
            if open_browser:
                webbrowser.open(state["url"])
        try:
            root.after(0, apply)
        except Exception:
            pass

    def supervise():
        opened = False
        bind_retries = 0
        while not stop.is_set():
            host, port = state["host"], state["port"]
            state["url"] = _browser_url(host, port)
            health = state["url"] + "api/health/ready"
            proc = start_server(bundle, host, port)
            state["proc"] = proc
            up = wait_until_up(health, proc)
            if up:
                bind_retries = 0
            opened = report_startup_result(
                up, proc, state["url"], update_ui, opened)
            code = proc.wait()
            state["proc"] = None
            if stop.is_set():
                break
            if code == RESTART_EXIT_CODE:
                state["host"], state["port"] = _consume_restart_request(
                    bundle, host, port)
                update_ui("Restarting the server…")
                continue
            # A different process can claim the tiny gap between pick_port() and
            # bind. Retry only that identifiable case; real startup failures stay
            # visible instead of being hidden in a restart loop.
            if not up and not _port_free(port) and bind_retries < 2:
                bind_retries += 1
                state["port"] = pick_port()
                update_ui("Selected port became busy; trying another…")
                continue
            update_ui("⚠️ The server stopped.\nSee data\\server.log for details.")
            break

    threading.Thread(target=supervise, daemon=True).start()
    root.mainloop()
    return 0


def _fatal(message: str) -> None:
    """Best-effort error dialog when we can't even reach the Tk UI path."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(APP_NAME, message)
        r.destroy()
    except Exception:
        sys.stderr.write(message + "\n")


if __name__ == "__main__":
    sys.exit(main())
