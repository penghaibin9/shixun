#!/usr/bin/env bash
# 独立 Linux Node Agent 的启动前检查。只读检查，不创建容器、不拉取镜像、不安装服务。
set -euo pipefail
IFS=$'\n\t'

config_path="${1:-/etc/yueke-node-agent/node-agent.env}"
python_path="${2:-/opt/yueke-node-agent/current/.venv/bin/python}"

fail() {
  printf '%s\n' "节点代理启动前检查失败：$*" >&2
  exit 1
}

[[ "$(uname -s)" == "Linux" ]] || fail "仅支持 Linux 节点"
[[ -f "$config_path" && ! -L "$config_path" && -r "$config_path" ]] || fail "配置文件必须是可读的普通文件"
[[ -x "$python_path" ]] || fail "未找到受控 Python 解释器"

for forbidden in DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH; do
  [[ -z "${!forbidden:-}" ]] || fail "不得通过 ${forbidden} 指向远程 Docker Engine"
done

"$python_path" - "$config_path" <<'PY'
from __future__ import annotations

import ipaddress
import re
import stat
import sys
from pathlib import Path, PurePosixPath


def fail(message: str) -> None:
    raise SystemExit(f"节点代理启动前检查失败：{message}")


path = Path(sys.argv[1])
metadata = path.stat()
if not stat.S_ISREG(metadata.st_mode):
    fail("配置文件不是普通文件")
if metadata.st_uid != 0:
    fail("配置文件必须由 root 持有，服务账户不得能够改写它")
if stat.S_IMODE(metadata.st_mode) & 0o137:
    fail("配置文件只允许 root 读写与服务组只读，禁止执行、组写和其他用户访问")

allowed_keys = {
    "YUEKE_NODE_AGENT_BIND_HOST",
    "YUEKE_NODE_AGENT_PORT",
    "YUEKE_NODE_AGENT_TOKEN",
    "YUEKE_AGENT_ALLOWED_DIGESTS",
    "YUEKE_AGENT_GRADER_DIGEST",
    "YUEKE_AGENT_CAPTURE_DIGEST",
    "YUEKE_AGENT_CAPTURE_DIR",
    "YUEKE_AGENT_CAPTURE_MAX_BYTES",
}
values: dict[str, str] = {}
for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    key, separator, value = line.partition("=")
    if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        fail(f"第 {number} 行不是安全的 KEY=VALUE 配置")
    if key not in allowed_keys:
        fail(f"第 {number} 行包含未允许的配置项 {key}")
    if key in values or value != value.strip() or any(character in value for character in "\x00\r\n"):
        fail(f"第 {number} 行配置格式无效")
    values[key] = value

missing = sorted(allowed_keys - set(values))
if missing:
    fail("缺少配置项：" + ", ".join(missing))

token = values["YUEKE_NODE_AGENT_TOKEN"]
if len(token) < 32 or len(token) > 512 or any(character.isspace() for character in token):
    fail("YUEKE_NODE_AGENT_TOKEN 必须为 32 至 512 个非空白字符")

digest_pattern = re.compile(r"sha256:[0-9a-f]{64}")
digests = values["YUEKE_AGENT_ALLOWED_DIGESTS"].split(",")
if not digests or any(not digest_pattern.fullmatch(digest) for digest in digests) or len(set(digests)) != len(digests):
    fail("YUEKE_AGENT_ALLOWED_DIGESTS 必须是无重复的固定 sha256 摘要列表")
for key in ("YUEKE_AGENT_GRADER_DIGEST", "YUEKE_AGENT_CAPTURE_DIGEST"):
    if values[key] not in digests:
        fail(f"{key} 必须位于 YUEKE_AGENT_ALLOWED_DIGESTS")

try:
    bind_address = ipaddress.ip_address(values["YUEKE_NODE_AGENT_BIND_HOST"])
except ValueError:
    fail("YUEKE_NODE_AGENT_BIND_HOST 必须是 IP 地址，不能使用主机名")
if not (bind_address.is_loopback or bind_address.is_private):
    fail("节点代理仅可绑定回环或私有地址，禁止公网、全网和多播地址")

try:
    port = int(values["YUEKE_NODE_AGENT_PORT"])
except ValueError:
    fail("YUEKE_NODE_AGENT_PORT 必须是整数")
if not 1024 <= port <= 65535:
    fail("YUEKE_NODE_AGENT_PORT 必须在 1024 至 65535 之间")

capture_root = PurePosixPath(values["YUEKE_AGENT_CAPTURE_DIR"])
if (
    not capture_root.is_absolute()
    or ".." in capture_root.parts
    or not str(capture_root).startswith("/var/lib/yueke-node-agent/")
):
    fail("YUEKE_AGENT_CAPTURE_DIR 必须位于 /var/lib/yueke-node-agent/ 下")
try:
    capture_limit = int(values["YUEKE_AGENT_CAPTURE_MAX_BYTES"])
except ValueError:
    fail("YUEKE_AGENT_CAPTURE_MAX_BYTES 必须是整数")
if not 1024 * 1024 <= capture_limit <= 128 * 1024 * 1024:
    fail("YUEKE_AGENT_CAPTURE_MAX_BYTES 必须在 1 MiB 至 128 MiB 之间")

print("节点代理配置字段检查通过（未输出令牌或配置值）")
PY

script_path="$(cd "$(dirname "$0")" && pwd -P)/$(basename "$0")"
agent_root="$(cd "$(dirname "$0")/../../../node_agent" && pwd -P)"
[[ -d "$agent_root" ]] || fail "无法定位 node_agent 源码目录"
"$python_path" - "$agent_root" "$python_path" "$script_path" <<'PY'
from __future__ import annotations

import stat
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"节点代理启动前检查失败：{message}")


agent_root = Path(sys.argv[1])
python_entry = Path(sys.argv[2])
venv_root = python_entry.parent.parent.resolve()
python_entry = venv_root / "bin" / "python"
python_target = python_entry.resolve()
script_path = Path(sys.argv[3]).resolve()
release_root = agent_root.parent
trusted_root = Path("/opt/yueke-node-agent")
expected_prefix = trusted_root / "releases"
try:
    release_root.relative_to(expected_prefix)
    script_path.relative_to(release_root)
    venv_root.relative_to(release_root)
except ValueError:
    fail("代码、解释器和启动脚本必须位于 /opt/yueke-node-agent/releases/ 的同一受控发行目录")
for label, target in (
    ("Node Agent 发布根目录", trusted_root),
    ("Node Agent 发布目录", expected_prefix),
    ("当前发行目录", release_root),
    ("node_agent 源码目录", agent_root),
    ("Node Agent 启动前检查脚本", script_path),
    ("Node Agent 虚拟环境", venv_root),
    ("Node Agent 解释器入口", python_entry),
    ("Node Agent 解释器目标", python_target),
    ("node_agent/app.py", agent_root / "app.py"),
):
    metadata = target.stat()
    if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
        fail(f"{label} 必须由 root 持有且不得被组或其他用户改写")
print("节点代理代码与解释器权限检查通过")
PY
(
  cd "$agent_root"
  "$python_path" -c 'import fastapi, uvicorn; from app import app; assert app.title == "跃科实验节点代理"'
) || fail "节点代理 Python 依赖或应用导入失败"

command -v docker >/dev/null 2>&1 || fail "未找到 docker 命令"
docker_context="$(docker context show 2>/dev/null)" || fail "无法读取 Docker context"
[[ "$docker_context" == "default" ]] || fail "仅允许 Docker default context，拒绝远程或自定义 context"
docker_host="$(docker context inspect "$docker_context" --format '{{(index .Endpoints "docker").Host}}' 2>/dev/null)" || fail "无法读取 Docker context 端点"
case "$docker_host" in
  unix:///var/run/docker.sock|unix:///run/docker.sock) ;;
  *) fail "Docker context 必须指向本机 Unix socket，当前端点不允许" ;;
esac
[[ "$(docker info --format '{{.OSType}}' 2>/dev/null)" == "linux" ]] || fail "节点必须连接 Linux Docker Engine"

printf '%s\n' "节点代理启动前检查通过（未创建 Docker 资源）"
