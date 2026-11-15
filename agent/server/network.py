"""Определение сетевых адресов ПК, по которым до агента достучится телефон."""

import ipaddress
import socket
from typing import Any

import psutil

_VIRTUAL_HINTS = (
    "vethernet", "wsl", "docker", "virtualbox", "vmware", "hyper-v",
    "loopback", "npcap", "vpn", "radmin", "hamachi", "zerotier",
    "xray", "v2ray", "wintun", "wireguard", "openvpn", "tap-", "tun",
    "happ", "clash", "sing-box", "outline", "nekoray", "hiddify", "warp",
    "amnezia", "bluetooth", "teredo",
)
# Производители виртуальных адаптеров: TAP-Windows, Hyper-V, VMware, VirtualBox
_VIRTUAL_OUI = ("00-FF-", "00-15-5D", "00-05-69", "00-0C-29", "00-50-56", "08-00-27", "0A-00-27")
_WIFI_HINTS = ("wi-fi", "wifi", "wlan", "wireless", "беспровод")
_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def _default_route_ip() -> str | None:
    """IP интерфейса с маршрутом по умолчанию (пакеты не отправляются)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _is_virtual_mac(mac: str | None) -> bool:
    """Нет MAC (TUN-адаптеры VPN), локально назначенный MAC или OUI виртуалки."""
    if not mac or set(mac.replace("-", "").replace(":", "")) <= {"0"}:
        return True
    mac = mac.upper().replace(":", "-")
    if int(mac[:2], 16) & 0x02:
        return True
    return mac.startswith(_VIRTUAL_OUI)


def _classify(iface: str, ip: str, mac: str | None) -> str:
    addr = ipaddress.ip_address(ip)
    if addr in _TAILSCALE_NET or "tailscale" in iface.lower():
        return "tailscale"
    if any(hint in iface.lower() for hint in _VIRTUAL_HINTS) or _is_virtual_mac(mac):
        return "virtual"
    if addr.is_private:
        return "lan"
    return "other"


def list_addresses() -> list[dict[str, Any]]:
    """Все IPv4-адреса ПК, отсортированные по вероятности, что они доступны с телефона."""
    primary = _default_route_ip()
    stats = psutil.net_if_stats()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for iface, addrs in psutil.net_if_addrs().items():
        st = stats.get(iface)
        if st is not None and not st.isup:
            continue
        mac = next((a.address for a in addrs if a.family == psutil.AF_LINK), None)
        for a in addrs:
            if a.family != socket.AF_INET:
                continue
            ip = a.address
            if ip in seen or ip.startswith(("127.", "169.254.")):
                continue
            seen.add(ip)
            result.append({
                "ip": ip,
                "iface": iface,
                "kind": _classify(iface, ip, mac),
                "wifi": any(h in iface.lower() for h in _WIFI_HINTS),
                "primary": ip == primary,
            })

    order = {"lan": 1, "tailscale": 2, "other": 3, "virtual": 4}
    result.sort(key=lambda r: (order.get(r["kind"], 9), not r["wifi"], not r["primary"], r["ip"]))
    return result


def best_ip() -> str:
    addrs = list_addresses()
    return addrs[0]["ip"] if addrs else "127.0.0.1"
