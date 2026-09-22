#!/usr/bin/env bash
# 对已启动的 Node Agent 做受保护健康与容量复核；不打印令牌、不创建 Docker 资源。
set -euo pipefail
IFS=$'\n\t'

config_path="${1:-/etc/yueke-node-agent/node-agent.env}"
agent_url="${2:-}"
python_path="${3:-/opt/yueke-node-agent/current/.venv/bin/python}"

[[ -f "$config_path" && ! -L "$config_path" && -r "$config_path" ]] || {
  printf '%s\n' "节点代理验证失败：配置文件必须是可读的普通文件" >&2
  exit 1
}
[[ -x "$python_path" ]] || {
  printf '%s\n' "节点代理验证失败：未找到受控 Python 解释器" >&2
  exit 1
}

"$python_path" - "$config_path" "$agent_url" <<'PY'
from __future__ import annotations

import ipaddress
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"节点代理验证失败：{message}")


path = Path(sys.argv[1])
values: dict[str, str] = {}
for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    key, separator, value = line.partition("=")
    if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
        fail(f"第 {number} 行配置格式无效")
    values[key] = value
token = values.get("YUEKE_NODE_AGENT_TOKEN", "")
bind_host = values.get("YUEKE_NODE_AGENT_BIND_HOST", "")
port = values.get("YUEKE_NODE_AGENT_PORT", "")
if len(token) < 32 or not bind_host or not port.isdecimal():
    fail("受保护验证所需配置不完整")

url = sys.argv[2].rstrip("/") or f"http://{bind_host}:{port}"
parsed = urllib.parse.urlparse(url)
if parsed.path or parsed.params or parsed.query or parsed.fragment or parsed.username or parsed.password:
    fail("验证地址只能是无路径、无凭据的服务根地址")
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    fail("验证地址必须是 http 或 https URL")
try:
    remote_address = ipaddress.ip_address(parsed.hostname)
    is_loopback = remote_address.is_loopback
except ValueError:
    is_loopback = parsed.hostname == "localhost"
if parsed.scheme == "http" and not is_loopback:
    fail("远程验证必须使用 HTTPS，避免传输控制面令牌")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


opener = urllib.request.build_opener(NoRedirect)


def request_json(endpoint: str) -> dict:
    request = urllib.request.Request(
        f"{url}{endpoint}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=5) as response:
            if response.status != 200:
                fail(f"{endpoint} 返回 HTTP {response.status}")
            payload = response.read(131073)
    except urllib.error.HTTPError as error:
        fail(f"{endpoint} 返回 HTTP {error.code}")
    except urllib.error.URLError as error:
        fail(f"{endpoint} 无法连接：{error.reason}")
    if len(payload) > 131072:
        fail(f"{endpoint} 响应过大")
    try:
        result = json.loads(payload)
    except json.JSONDecodeError:
        fail(f"{endpoint} 未返回 JSON")
    if not isinstance(result, dict):
        fail(f"{endpoint} 返回格式无效")
    return result


health = request_json("/health")
capacity = request_json("/capacity")
if health.get("status") != "ok" or not str(health.get("engine", "")).startswith("linux "):
    fail("健康响应未证明 Linux Docker Engine")
for key in ("cpu_total", "memory_total_mb", "cpu_available", "memory_available_mb", "running_groups", "image_digests"):
    if key not in capacity:
        fail(f"容量响应缺少 {key}")
print(
    json.dumps(
        {
            "status": "ok",
            "engine": health["engine"],
            "running_groups": capacity["running_groups"],
            "cpu_available": capacity["cpu_available"],
            "memory_available_mb": capacity["memory_available_mb"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY
