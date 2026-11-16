"""Build and verify a private Windows package; never upload or replace a build.

Run with an official 64-bit Windows Python 3.12+ installation including Tcl/Tk.
Each invocation copies the current source into a new build directory, creates
its own virtual environment and test profiles, and only creates a ZIP after
all required checks pass. No repository, language or execution-policy changes
are made. The offline wheel directory must contain all transitive dependencies.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import traceback
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("assistant_ai", "assets", "docs", "tests", "tools", ".github")
IGNORED_DIRS = {"__pycache__", ".git", ".venv", "venv", "build", "dist"}


class BuildError(RuntimeError):
    pass


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_version(root):
    module = ast.parse((root / "app_brand.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "APP_VERSION"
                                               for target in node.targets):
            version = ast.literal_eval(node.value)
            if isinstance(version, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+._a-zA-Z0-9]*)", version):
                return version
    raise BuildError("app_brand.py must contain a literal, filename-safe APP_VERSION.")


def source_files(root):
    # An explicit inventory includes untracked new code, but never user profile
    # JSON, a virtual environment, previous packages or Git credentials/history.
    files = [path for path in root.iterdir() if path.is_file() and
             (path.suffix.lower() in {".py", ".md", ".cmd"} or path.name in {"LICENSE", "requirements.txt"})]
    for name in SOURCE_DIRS:
        base = root / name
        if name == ".github" and not base.exists():
            continue  # A local source kit need not include CI configuration.
        if not base.is_dir():
            raise BuildError(f"Source directory is missing: {base}")
        if base.is_symlink() or base.is_junction():
            raise BuildError(f"Source directory links are not copied: {base}")
        for directory, children, names in os.walk(base, followlinks=False):
            children[:] = sorted(child for child in children if child not in IGNORED_DIRS)
            if any((Path(directory) / child).is_symlink() or (Path(directory) / child).is_junction() for child in children):
                raise BuildError(f"Source directory contains a symbolic link: {directory}")
            files.extend(Path(directory) / name for name in names
                         if not name.endswith((".pyc", ".pyo", ".log")))
    for path in files:
        if path.is_symlink():
            raise BuildError(f"Source links are not copied: {path}")
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def snapshot_source(root, destination):
    destination.mkdir()
    paths = source_files(root)
    inventory = []
    for source in paths:
        relative = source.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
        inventory.append({"path": relative.as_posix(), "bytes": target.stat().st_size,
                          "sha256": digest_file(target)})
    if source_files(root) != paths or any(digest_file(root / item["path"]) != item["sha256"] for item in inventory):
        raise BuildError("Source changed while copying. Run the builder again after saving your edits.")
    encoded = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return inventory, hashlib.sha256(encoded).hexdigest()


def git_provenance(root):
    result = {"commit": None, "dirty": None, "note": "Git metadata unavailable; snapshot SHA-256 identifies the build."}
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], check=True,
                             capture_output=True, text=True, timeout=10).stdout.strip()
        if Path(top).resolve() != root.resolve():
            return result
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
                                check=True, capture_output=True, text=True, timeout=10).stdout
        result = {"commit": commit, "dirty": bool(status), "note": "Build uses the copied working files, including untracked files."}
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def write_json(path, content):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(content, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def child_environment(profile, python=None):
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE", "PYTHONINSPECT", "PYSTRAY_BACKEND", "TCL_LIBRARY", "TK_LIBRARY"):
        env.pop(name, None)
    profile.mkdir(parents=True)
    env.update(APPDATA=str(profile), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
               PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1")
    if python is not None:
        env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(python.parent.parent)
    return env


def windows_job():
    """Keep every build/test descendant tied to an owned Windows job handle."""
    import ctypes as C
    from ctypes import wintypes as W

    class Basic(C.Structure):
        _fields_ = [("process_time", C.c_longlong), ("job_time", C.c_longlong), ("flags", W.DWORD),
                    ("minimum", C.c_size_t), ("maximum", C.c_size_t), ("active", W.DWORD),
                    ("affinity", C.c_size_t), ("priority", W.DWORD), ("scheduling", W.DWORD)]

    class IO(C.Structure):
        _fields_ = [(name, C.c_ulonglong) for name in ("read_ops", "write_ops", "other_ops", "read", "write", "other")]

    class Extended(C.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", C.c_size_t),
                    ("job_memory", C.c_size_t), ("peak_process", C.c_size_t), ("peak_job", C.c_size_t)]

    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = (C.c_void_p, W.LPCWSTR), W.HANDLE
    kernel.SetInformationJobObject.argtypes = (W.HANDLE, C.c_int, C.c_void_p, W.DWORD)
    kernel.SetInformationJobObject.restype = W.BOOL
    kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = (W.HANDLE, W.HANDLE), W.BOOL
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = (W.HANDLE,), W.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise C.WinError(C.get_last_error())
    settings = Extended()
    settings.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, C.byref(settings), C.sizeof(settings)):
        error = C.WinError(C.get_last_error())
        kernel.CloseHandle(handle)
        raise error
    return kernel, handle


def resume_child(pid, kernel):
    """Resume a newly created, suspended primary thread after job assignment."""
    import ctypes as C
    from ctypes import wintypes as W

    class ThreadEntry(C.Structure):
        _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("thread", W.DWORD),
                    ("owner", W.DWORD), ("base_priority", W.LONG),
                    ("delta_priority", W.LONG), ("flags", W.DWORD)]

    kernel.CreateToolhelp32Snapshot.argtypes, kernel.CreateToolhelp32Snapshot.restype = (W.DWORD, W.DWORD), W.HANDLE
    kernel.Thread32First.argtypes, kernel.Thread32First.restype = (W.HANDLE, C.POINTER(ThreadEntry)), W.BOOL
    kernel.Thread32Next.argtypes, kernel.Thread32Next.restype = (W.HANDLE, C.POINTER(ThreadEntry)), W.BOOL
    kernel.OpenThread.argtypes, kernel.OpenThread.restype = (W.DWORD, W.BOOL, W.DWORD), W.HANDLE
    kernel.ResumeThread.argtypes, kernel.ResumeThread.restype = (W.HANDLE,), W.DWORD
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    resumed = False
    try:
        entry = ThreadEntry()
        entry.size = C.sizeof(entry)
        found = kernel.Thread32First(snapshot, C.byref(entry))
        while found:
            if entry.owner == pid:
                thread = kernel.OpenThread(0x0002, False, entry.thread)  # THREAD_SUSPEND_RESUME
                if not thread:
                    raise C.WinError(C.get_last_error())
                try:
                    count = kernel.ResumeThread(thread)
                    if count == 0xFFFFFFFF:
                        raise C.WinError(C.get_last_error())
                    resumed = resumed or count > 0
                finally:
                    kernel.CloseHandle(thread)
            found = kernel.Thread32Next(snapshot, C.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    if not resumed:
        raise BuildError("Could not resume the isolated build/test process.")


@contextmanager
def process(command, *, cwd, env, log):
    import ctypes
    kernel, job = windows_job()
    child = None
    try:
        with Path(log).open("xb") as stream:
            child = subprocess.Popen([str(part) for part in command], cwd=cwd, env=env,
                                     stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=0x00000004)  # CREATE_SUSPENDED: no pre-assignment children.
            if not kernel.AssignProcessToJobObject(job, int(child._handle)):
                error = ctypes.WinError(ctypes.get_last_error())
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=15)
                raise BuildError(f"Cannot isolate the child process tree: {error}")
            resume_child(child.pid, kernel)
            yield child
    finally:
        kernel.CloseHandle(job)  # Includes descendants on timeout, failure or Ctrl+C.
        if child is not None:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=15)
                child.wait(timeout=10)


def run(command, label, *, cwd, env, logs, timeout=1200, accepted=(0,)):
    log = logs / (label + ".log")
    print(f"[{label}] Log: {log}", flush=True)
    with process(command, cwd=cwd, env=env, log=log) as child:
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise BuildError(f"{label} exceeded {timeout} seconds. See {log}") from error
    if code not in accepted:
        raise BuildError(f"{label} failed (exit {code}). See {log}")
    return code


def validate_ui_report(path, version):
    report = json.loads(path.read_text(encoding="utf-8"))
    checks = report.get("checks", [])
    if report.get("status") != "passed" or report.get("version") != version or report.get("api_calls") != 0 \
            or report.get("isolated_profile") is not True or {item.get("dpi") for item in checks} != {96, 120, 144, 192}:
        raise BuildError("Packaged UI report did not confirm this version at all four DPI values.")
    flags = ("saved_without_apply", "manual_preserved", "manifest_reopened", "reselected", "undo")
    for item in checks:
        named = item.get("named_images", {})
        if item.get("status") != "passed" or named.get("roles") != 10 or not all(named.get(key) is True for key in flags):
            raise BuildError("Packaged named-image-set checks are missing or failed.")
    return report


def normal_start(executable, profile, logs):
    env = child_environment(profile)
    print("[normal-start] Close any older timer. Testing the normal entrypoint for 8 seconds.", flush=True)
    with process([executable], cwd=executable.parent, env=env, log=logs / "normal-start.log") as child:
        try:
            code = child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise BuildError(f"Normal startup exited early ({code}). Close any older running timer and retry.")
    app_log = profile / "KyungheeAssistant" / "kyunghee.log"
    if not app_log.is_file():
        raise BuildError("Normal startup did not create its isolated application log.")
    content = app_log.read_text(encoding="utf-8", errors="replace")
    if re.search(r"tray failed|asset failed|tick failed|Traceback|\bERROR\b", content, re.IGNORECASE):
        raise BuildError(f"Normal startup logged an error: {app_log}")
    shutil.copyfile(app_log, logs / "normal-start-application.log")
    return {"status": "passed", "seconds": 8, "isolated_profile": True,
            "evidence": "Normal entrypoint with unpatched Windows tray path survived; no startup errors in its log.",
            "limitations": "Does not establish physical tray interaction, sleep or real-monitor behavior."}


def build(args):
    version = read_version(ROOT)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir.expanduser().resolve()
    if any(output == ROOT / name or (ROOT / name) in output.parents for name in SOURCE_DIRS):
        raise BuildError("The output directory cannot be inside a source input directory (assets, tools, tests, etc.).")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"SeungaTimer-{version}-{stamp}-{uuid.uuid4().hex[:8]}"
    destination.mkdir()  # Exclusive reservation; existing builds are never reused.
    print(f"Build directory: {destination}", flush=True)
    logs, reports = destination / "logs", destination / "reports"
    logs.mkdir()
    reports.mkdir()
    archive = None
    archive_published = False
    try:
        source = destination / "source"
        inventory, snapshot_hash = snapshot_source(ROOT, source)
        if read_version(source) != version:
            raise BuildError("Version changed while preparing the source snapshot.")
        provenance = git_provenance(ROOT)
        write_json(reports / "source-manifest.json", {"sha256": snapshot_hash, "files": inventory})
        env = child_environment(destination / "profiles" / "build")
        env["PYINSTALLER_CONFIG_DIR"] = str(destination / "pyinstaller-cache")
        env["PIP_CACHE_DIR"] = str(destination / "pip-cache")
        venv = destination / "venv"
        run([sys.executable, "-m", "venv", venv], "create-environment", cwd=source, env=env, logs=logs)
        python = venv / "Scripts" / "python.exe"
        env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(venv)
        install = [python, "-m", "pip", "install", "--no-input"]
        if args.wheel_dir is not None:
            wheels = args.wheel_dir.expanduser().resolve()
            if not wheels.is_dir():
                raise BuildError(f"Offline wheel directory is missing: {wheels}")
            # Ignore user pip indexes/find-links configuration in offline mode.
            # Only the supplied local wheel directory may provide packages.
            for key in list(env):
                if key.startswith("PIP_"):
                    env.pop(key)
            env["PIP_CONFIG_FILE"] = os.devnull
            env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
            env["PIP_CACHE_DIR"] = str(destination / "pip-cache")
            install += ["--no-index", "--find-links", wheels]
        run([*install, "-r", source / "requirements.txt", "pyinstaller>=6.6"], "dependencies", cwd=source, env=env, logs=logs)
        run([python, "-m", "pip", "freeze", "--all"], "dependency-versions", cwd=source, env=env, logs=logs)
        test_env = child_environment(destination / "profiles" / "unit-tests", python)
        run([python, "-m", "unittest", "discover", "-s", "tests", "-v"], "unit-tests",
            cwd=source, env=test_env, logs=logs, timeout=1800)
        run([python, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
             "--optimize", "0",
             "--name", "SeungaTimer", "--add-data", f"{source / 'assets'};assets", "--distpath", destination / "dist",
             "--workpath", destination / "build", "--specpath", destination, source / "desktop_gallery_final.py"],
            "pyinstaller", cwd=source, env=env, logs=logs)
        package = destination / "dist" / "SeungaTimer"
        executable = package / "SeungaTimer.exe"
        if not executable.is_file() or not (package / "_internal").is_dir():
            raise BuildError("PyInstaller did not produce the complete onedir package.")
        ui_path = reports / "packaged-ui-report.json"
        run([executable, "--self-test", ui_path], "packaged-ui", cwd=package,
            env=child_environment(destination / "profiles" / "packaged-ui"), logs=logs, timeout=240)
        validate_ui_report(ui_path, version)
        startup = normal_start(executable, destination / "profiles" / "normal-start", logs)
        print("[IME] A separate local input check will open. Keep your keyboard and mouse idle during it.", flush=True)
        ime_path = reports / "packaged-ime-report.json"
        ime_exit = run([executable, "--ime-self-test", ime_path], "packaged-ime", cwd=package,
                       env=child_environment(destination / "profiles" / "ime"), logs=logs, timeout=240, accepted=(0, 3))
        ime = json.loads(ime_path.read_text(encoding="utf-8"))
        expected = "passed" if ime_exit == 0 else "unavailable"
        if ime.get("status") != expected or ime.get("network_attempts") != 0 or ime.get("real_api_calls") != 0:
            raise BuildError("Packaged IME report is missing, inconsistent, or reported a network attempt.")
        if ime_exit == 0 and not (ime.get("real_composition_observed") and ime.get("microsoft_korean_identity_verified")):
            raise BuildError("IME pass does not include verified Microsoft Korean composition evidence.")
        if ime_exit == 3:
            print("IME UNAVAILABLE (not a pass): " + str(ime.get("reason", "See report")), flush=True)
        for name in ("README.md", "LICENSE", "WINDOWS_SMOKE_TEST.md", "IME_INPUT_TEST.cmd"):
            shutil.copyfile(source / name, package / name)
        shutil.copytree(source / "docs", package / "docs")
        summary = {"version": version, "created_at": datetime.now(timezone.utc).isoformat(),
                   "source_snapshot_sha256": snapshot_hash, "git": provenance,
                   "build_host": platform.platform(), "python": sys.version, "unit_tests": "passed",
                   "packaged_ui": "passed", "normal_start": startup,
                   "ime_status": expected, "ime_reason": ime.get("reason"),
                   "physical_windows_validation": "Not established by automated checks.",
                   "published": False}
        write_json(reports / "build-verification.json", summary)
        for path in reports.iterdir():
            if path.is_file():
                shutil.copyfile(path, package / path.name)
        shutil.copyfile(logs / "dependency-versions.log", package / "DEPENDENCY_VERSIONS.txt")
        info = (f"Seunga Timer {version}\nBuilt: {summary['created_at']}\n"
                f"Source snapshot SHA-256: {snapshot_hash}\n"
                f"Git commit: {provenance['commit'] or 'unavailable'}\nGit dirty: {provenance['dirty']}\n"
                f"Builder: {summary['build_host']}\nPython: {sys.version}\n"
                f"Unit tests and packaged four-DPI UI: passed\nNormal startup: 8 seconds\nIME: {expected}\n"
                "No physical Windows/monitor/sleep/IME-user-scenario claim. See JSON reports.\n"
                "Local build only; no source upload, branch push or public release.\n"
                "Close the older timer. Extract to a NEW folder and keep SeungaTimer.exe beside _internal.\n")
        with (package / "BUILD_INFO.txt").open("x", encoding="utf-8") as stream:
            stream.write(info)
        archive = destination / f"SeungaTimer-{version}-windows-x64-{stamp}.zip"
        partial = archive.with_suffix(".zip.partial")
        try:
            with partial.open("xb") as stream, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zipped:
                for path in sorted(package.rglob("*")):
                    if path.is_file():
                        zipped.write(path, Path("SeungaTimer") / path.relative_to(package))
            with zipfile.ZipFile(partial) as zipped:
                failed = zipped.testzip()
                if failed is not None:
                    raise BuildError(f"ZIP verification failed: {failed}")
            checksum = digest_file(partial)
            with archive.with_suffix(".zip.sha256").open("x", encoding="ascii") as stream:
                stream.write(f"{checksum}  {archive.name}\n")
            # Windows rename refuses an existing destination. The directory was
            # also reserved exclusively, so no older ZIP can be replaced.
            partial.rename(archive)
            archive_published = True
        finally:
            partial.unlink(missing_ok=True)
        print(f"\nVerified local package: {archive}\nSHA-256: {checksum}\nIME: {expected}", flush=True)
        return 0
    except BaseException:
        if archive_published:
            archive.unlink(missing_ok=True)
        with (destination / "BUILD_FAILED.txt").open("x", encoding="utf-8") as stream:
            stream.write(traceback.format_exc())
        print(f"Build failed. No deliverable ZIP should be used. Logs: {logs}", file=sys.stderr, flush=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wheel-dir", type=Path, help="Offline Windows wheels for runtime, PyInstaller and all dependencies (pip --no-index).")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist" / "local-windows",
                        help="Parent for a new version/timestamp build directory; existing directories are never reused.")
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("This builder requires Windows Python. Linux Python cannot produce this Windows package.")
    if sys.version_info < (3, 12) or struct.calcsize("P") != 8:
        parser.error("Use a 64-bit Windows Python 3.12 or newer, with Tcl/Tk and pip installed.")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("The current package target is Windows x64; use an x64 Python installation.")
    print("Local Windows build: no uploads or repository changes. Close any running Seunga Timer before validation.")
    try:
        return build(args)
    except (BuildError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Build cancelled; see the new build directory for logs.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
