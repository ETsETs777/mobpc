import asyncio
import base64
import binascii
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

import psutil

from server.config import settings

# Принудительно UTF-8 для PowerShell, иначе русская Windows отдаёт вывод в cp866 и кириллица ломается.
_PS_PREFIX = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $OutputEncoding=[Text.Encoding]::UTF8; "
SHELL_MAP = {
    "powershell": (["powershell", "-NoProfile", "-NonInteractive", "-Command"], _PS_PREFIX),
    "cmd": (["cmd", "/d", "/s", "/c"], ""),
}


def _oem_encoding() -> str:
    try:
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except Exception:
        return "cp866"


_OEM = _oem_encoding()


def decode_output(chunk: bytes) -> str:
    """PowerShell отдаёт UTF-8, а cmd без консоли — OEM-кодировку (cp866 в русской Windows)."""
    try:
        return chunk.decode("utf-8")
    except UnicodeDecodeError:
        return chunk.decode(_OEM, errors="replace")


async def exec_shell(
    payload: dict[str, Any],
    on_stream: Optional[Callable[[str, str], Any]] = None,
) -> dict[str, Any]:
    command = payload.get("command", "")
    if not command:
        raise ValueError("command is required")
    shell = payload.get("shell", "powershell")
    if shell not in SHELL_MAP:
        raise ValueError(f"Unknown shell: {shell}")
    timeout = float(payload.get("timeout", settings.shell_timeout_seconds))
    cwd = payload.get("cwd") or None
    if cwd and not Path(cwd).is_dir():
        raise FileNotFoundError(cwd)

    base, prefix = SHELL_MAP[shell]
    proc = await asyncio.create_subprocess_exec(
        *base, prefix + command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        cwd=cwd,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    async def read_stream(stream, name: str, parts: list[str]) -> None:
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            text = decode_output(chunk)
            parts.append(text)
            if on_stream:
                result = on_stream(name, text)
                if asyncio.iscoroutine(result):
                    await result

    timed_out = False
    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(proc.stdout, "stdout", stdout_parts),
                read_stream(proc.stderr, "stderr", stderr_parts),
            ),
            timeout=timeout,
        )
        exit_code = await proc.wait()
    except asyncio.TimeoutError:
        timed_out = True
        exit_code = -1
    finally:
        # Отмена (клиент отключился) или таймаут — процесс не должен остаться висеть.
        if proc.returncode is None:
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), 5)
            except (ProcessLookupError, asyncio.TimeoutError):
                pass
    if timed_out:
        stderr_parts.append(f"\n[mobpc] Команда остановлена по таймауту {int(timeout)} с\n")
    return {
        "exit_code": exit_code,
        "stdout": "".join(stdout_parts),
        "stderr": "".join(stderr_parts),
        "timed_out": timed_out,
    }


class FileExecutor:
    def list_drives(self) -> dict[str, Any]:
        entries = []
        for part in psutil.disk_partitions(all=False):
            try:
                total = psutil.disk_usage(part.mountpoint).total
            except OSError:
                total = 0
            entries.append({"name": part.mountpoint, "is_dir": True, "size": total, "drive": True})
        return {"path": "", "parent": None, "entries": entries}

    def list_dir(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("path")
        if raw == "" or raw == "::drives":
            return self.list_drives()
        path = Path(raw or "C:\\").expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))
        if not path.is_dir():
            raise NotADirectoryError(str(path))
        entries = []
        for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size": stat.st_size if item.is_file() else 0,
                    "mtime": int(stat.st_mtime),
                })
            except OSError:
                continue
        parent = str(path.parent) if path.parent != path else ""
        return {"path": str(path), "parent": parent, "entries": entries}

    def read_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = Path(payload["path"])
        offset = int(payload.get("offset", 0))
        length = int(payload.get("length", 65536))
        if offset < 0 or not 0 <= length <= settings.max_ws_file_bytes:
            raise ValueError("Недопустимый диапазон чтения файла")
        if not path.is_file():
            raise FileNotFoundError(str(path))
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(length)
        return {
            "path": str(path),
            "offset": offset,
            "size": size,
            "data": base64.b64encode(data).decode("ascii"),
        }

    def write_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = Path(payload["path"])
        encoded = payload["data"]
        if not isinstance(encoded, str):
            raise ValueError("Данные файла должны быть строкой Base64")
        if len(encoded) > 4 * ((settings.max_ws_file_bytes + 2) // 3):
            raise ValueError("Файл слишком большой для WebSocket")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Некорректные данные Base64") from exc
        if len(data) > settings.max_ws_file_bytes:
            raise ValueError("Файл слишком большой для WebSocket")
        append = payload.get("append", False)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if append else "wb"
        with open(path, mode) as f:
            f.write(data)
        return {"path": str(path), "written": len(data)}

    def delete_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = Path(payload["path"])
        if path.is_dir():
            import shutil
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
        else:
            raise FileNotFoundError(str(path))
        return {"deleted": str(path)}

    def download_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = Path(payload["path"])
        if not path.is_file():
            raise FileNotFoundError(str(path))
        if path.stat().st_size > settings.max_ws_file_bytes:
            raise ValueError("Файл слишком большой для WebSocket — используйте GET /api/files/download")
        data = path.read_bytes()
        return {
            "name": path.name,
            "size": len(data),
            "data": base64.b64encode(data).decode("ascii"),
        }


file_executor = FileExecutor()
