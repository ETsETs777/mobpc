import subprocess
from typing import Any


class NotifyExecutor:
    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = payload.get("title", "mobpc")
        message = payload.get("message", "")
        ps = (
            f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; '
            f'[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; '
            f'$template = @"<toast><visual><binding template="ToastText02"><text id="1">{title}</text><text id="2">{message}</text></binding></visual></toast>"@; '
            f'$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; $xml.LoadXml($template); '
            f'$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); '
            f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("mobpc").Show($toast)'
        )
        try:
            subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            # Fallback: msg command
            subprocess.run(["msg", "*", f"{title}: {message}"], capture_output=True)
        return {"sent": True, "title": title, "message": message}


notify_executor = NotifyExecutor()
