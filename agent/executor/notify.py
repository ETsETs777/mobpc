import os
import subprocess
from typing import Any

# Текст передаётся через переменные окружения и экранируется в самом PowerShell,
# поэтому кавычки/`$()` в сообщении не могут выполниться как код.
_TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [Security.SecurityElement]::Escape($env:MOBPC_TITLE)
$m = [Security.SecurityElement]::Escape($env:MOBPC_MESSAGE)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastText02'><text id='1'>$t</text><text id='2'>$m</text></binding></visual></toast>")
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


class NotifyExecutor:
    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title", "mobpc"))[:120]
        message = str(payload.get("message", ""))[:500]
        env = {**os.environ, "MOBPC_TITLE": title, "MOBPC_MESSAGE": message}
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST_PS],
                capture_output=True,
                timeout=15,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            ok = proc.returncode == 0
        except Exception:
            ok = False
        if not ok:
            # Запасной вариант: системное окно сообщения.
            subprocess.run(["msg", "*", f"{title}: {message}"], capture_output=True)
        return {"sent": True, "title": title, "message": message}


notify_executor = NotifyExecutor()
