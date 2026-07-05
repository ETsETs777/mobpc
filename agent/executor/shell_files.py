import asyncio
import base64
import os
import subprocess
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

SHELL_MAP = {
    "powershell": ["powershell", "-NoProfile", "-Command"],
    "cmd": ["cmd", "/c"],
}


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

    args = SHELL_MAP[shell] + [command]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    async def read_stream(stream, name: str, parts: list[str]) -> None:
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            parts.append(text)
            if on_stream:
                result = on_stream(name, text)
                if asyncio.iscoroutine(result):
                    await result

    await asyncio.gather(
        read_stream(proc.stdout, "stdout", stdout_parts),
        read_stream(proc.stderr, "stderr", stderr_parts),
    )
    exit_code = await proc.wait()
    return {
        "exit_code": exit_code,
        "stdout": "".join(stdout_parts),
        "stderr": "".join(stderr_parts),
    }


class FileExecutor:
    def list_dir(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = Path(payload.get("path") or "C:\\")
        if not path.exists():
            raise FileNotFoundError(str(path))
        entries = []
        for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size": stat.st_size if item.is_file() else 0,
                })
            except OSError:
                continue
        return {"path": str(path), "entries": entries}

    def read_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = Path(payload["path"])
        offset = int(payload.get("offset", 0))
        length = int(payload.get("length", 65536))
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
        data = base64.b64decode(payload["data"])
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
        data = path.read_bytes()
        return {
            "name": path.name,
            "size": len(data),
            "data": base64.b64encode(data).decode("ascii"),
        }


file_executor = FileExecutor()
