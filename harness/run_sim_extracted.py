"""Run Observathon sim while bypassing the broken PyInstaller bootloader.

On this Windows machine, the bundled exe fails while loading python312.dll.
This runner extracts the Python archive from the exe and runs the simulator with
the system Python 3.12 instead.
"""
from __future__ import annotations

import importlib.util
import os
import struct
import sys
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / ".pyi-full"
CODE = ROOT / ".pyi-code"
MAGIC = b"MEI\014\013\012\013\016"


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def extract_code(exe: Path) -> None:
    FULL.mkdir(exist_ok=True)
    CODE.mkdir(exist_ok=True)
    data = exe.read_bytes()
    pos = data.rfind(MAGIC)
    if pos < 0:
        raise RuntimeError(f"not a PyInstaller archive: {exe}")

    _, pkg_len, toc_pos, toc_len, _pyver, _pylib = struct.unpack("!8sIIII64s", data[pos : pos + 88])
    archive_start = len(data) - pkg_len
    toc = data[archive_start + toc_pos : archive_start + toc_pos + toc_len]

    p = 0
    while p < len(toc):
        entry_size = struct.unpack("!I", toc[p : p + 4])[0]
        raw = toc[p : p + entry_size]
        if len(raw) < 18:
            break
        entry_size, offset, compressed_len, uncompressed_len, compressed, typecode = struct.unpack(
            "!IIIIBc", raw[:18]
        )
        name = raw[18:].split(b"\0", 1)[0].decode("utf-8", "replace")
        p += entry_size

        blob = data[archive_start + offset : archive_start + offset + compressed_len]
        if compressed:
            blob = zlib.decompress(blob)
        if len(blob) != uncompressed_len:
            raise RuntimeError(f"bad extract size for {name}")

        kind = typecode.decode("latin1")
        if kind == "z":
            (FULL / name).write_bytes(blob)
        elif kind in ("m", "s"):
            header = importlib.util.MAGIC_NUMBER + b"\0\0\0\0" + b"\0" * 8
            (CODE / f"{name}.pyc").write_bytes(header + blob)


def main() -> None:
    load_dotenv()

    args = sys.argv[1:]
    phase = "practice"
    if len(args) >= 2 and args[0] == "--phase":
        phase = args[1]
        args = args[2:]
    elif args and args[0].startswith("--phase="):
        phase = args[0].split("=", 1)[1]
        args = args[1:]

    exe = ROOT / "bin" / phase / "observathon-sim" / "observathon-sim.exe"
    internal = exe.parent / "_internal"
    if not exe.exists() or not internal.exists():
        raise SystemExit(f"missing simulator onedir files under: {exe.parent}")

    extract_code(exe)
    sys.frozen = True  # type: ignore[attr-defined]
    sys._MEIPASS = str(internal)  # type: ignore[attr-defined]
    sys._pyinstaller_pyz = str(FULL / "PYZ.pyz")  # type: ignore[attr-defined]
    sys.executable = str(exe)

    # Keep stdlib ctypes from the host Python. Loading the archived/bundled copy
    # through PyInstaller's importer can break when we bypass the bootloader.
    import ctypes  # noqa: F401
    import ssl  # noqa: F401

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(CODE))
    sys.path.insert(0, str(FULL))
    sys.path.insert(0, str(internal))

    import pyimod02_importers

    pyimod02_importers.install()

    from observathon_sim.cli import main as sim_main

    sys.argv = [str(exe), *args]
    sim_main()


if __name__ == "__main__":
    main()
