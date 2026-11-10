"""网络安全工具：出站 URL 目标校验与 SSRF (Server-Side Request Forgery) 防御。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_or_loopback(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(addr in net for net in _BLOCKED_NETWORKS)


def validate_url_target(url: str) -> tuple[bool, str]:
    """通过解析协议、域名与 DNS 目标 IP 验证外部请求是否安全（防止访问内部服务与云元数据接口）。

    Returns:
        (ok, error_msg): ok 为 True 时 error_msg 为空；若解析出私有 IP、回环或云元数据地址，则拒绝。
    """
    try:
        p = urlparse(url)
    except Exception as e:
        return False, f"Malformed URL: {e}"

    if p.scheme not in ("http", "https"):
        return False, f"Only http/https protocols allowed, got '{p.scheme or 'none'}'"
    if not p.netloc:
        return False, "Missing domain/netloc"

    hostname = p.hostname
    if not hostname:
        return False, "Missing hostname"

    # 先检查是否直接为 IP 字面量
    try:
        direct_ip = ipaddress.ip_address(hostname)
        if _is_private_or_loopback(direct_ip):
            return False, f"Access to private/internal IP {direct_ip} is blocked for security"
        return True, ""
    except ValueError:
        pass

    # 通过 DNS 解析该主机名的所有 IP
    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, f"DNS resolution failed for '{hostname}': {e}"
    except Exception as e:
        return False, f"Address resolution error for '{hostname}': {e}"

    if not addr_infos:
        return False, f"No IP addresses resolved for hostname '{hostname}'"

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
            if _is_private_or_loopback(addr):
                return False, f"Hostname '{hostname}' resolved to blocked private/internal address {ip_str}"
        except ValueError:
            return False, f"Invalid resolved IP address: {ip_str}"

    return True, ""
