# D 线本地真实运行证据（2026-09-22）

环境：Docker Engine 29.7.2（Linux 容器）、MySQL 8.4、固定镜像 `python:3.11-bookworm@sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca`。控制面通过带身份令牌的 Node Agent 操作本机引擎，未向 Web/API 暴露 Docker Socket。

## 单学生闭环

- G4：PASS。控制面真实创建独立内部网络和双容器实例组，并可查询运行状态。
- G5：PARTIAL。浏览器同协议 WebSocket 使用首帧短期令牌进入非 root 学生容器并真实执行 OpenSSL 命令；令牌重放、30 秒真实过期和跨实例使用均返回 4403。当前 Node Agent（节点代理）运行在 Windows Python（解释器）进程，尚未证明 Linux POSIX/PTTY（伪终端）尺寸实际变化。
- G6：PASS。真实生成密钥、密文、解密结果、签名和报告；5 个检查点由独立、无网络、非 root 临时判定器执行，合计 100 分并写入 MySQL 与事件发件箱。
- 网络：`student → business mysql = DENY`、`student A → student B = DENY`、`student → same-group target/grader = ALLOW`。
- 恢复：重复启动保持同一请求；重建保留 100 分检查点事实；重复销毁成功且最终无残留跃科容器/网络。
- 流量采集：PASS。门禁自动构建并锁定专用抓包镜像摘要，运行组创建后启动采集，重建和销毁前停止；控制面从受鉴权接口取回并登记 3 份真实 PCAP（抓包文件），大小分别为 606、5697、606 字节，下载 ZIP（压缩包）解压后的大小、格式和 SHA256（文件校验值）逐项复核一致。抓包侧车仅增加 `NET_RAW（原始网络包）` 能力，未使用特权模式、宿主目录或 Docker Socket（容器运行接口）挂载，门禁结束后容器、镜像与临时目录均已清理。

执行入口：`scripts/run-runtime-gate.ps1`。可用 `-DatabaseName` 指定专属验收库，本次采集闭环使用从空库执行全部迁移的 `yueke_d_capture_gate`。

## 单节点容量阶梯

资源请求：每组 2 个容器，共 2 CPU、2048 MB 内存；节点实际总内存约 7774 MB。测试严格按 5 → 10 → 20 个请求递增，未把排队记为启动成功。

| 请求数 | 真实运行 | 排队 | 失败 | 累计耗时 | 节点剩余 CPU | 节点剩余内存 |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 3 | 2 | 0 | 31.682 秒 | 9.25 | 1245 MB |
| 10 | 3 | 7 | 0 | 48.332 秒 | 9.25 | 1245 MB |
| 20 | 3 | 17 | 0 | 81.788 秒 | 9.25 | 1245 MB |

结论：在当前 RSA 配额和每个运行组真实抓包旁车均启用的条件下，本机单节点实测并发容量为 3 组，限制因素是内存；不能依据原型宣称 50 组。测试结束后运行实例均已销毁，排队请求均已取消，容器、抓包旁车与网络清理通过。

执行入口：`scripts/run-runtime-gate.ps1 -GateScript tests/runtime_capacity_gate.py`。

## 尚未通过

- Node Agent（节点代理）仍以门禁进程运行，尚未安装为系统常驻服务。
- 当前 Docker Desktop（容器桌面环境）未启用 Ubuntu WSL（适用于 Linux 的 Windows 子系统）集成；根安全规则禁止向容器挂载宿主 Docker Socket，因此不能以不合规方式伪造 Linux Node Agent 证据。
- G5 严格门禁仍需在独立 Linux Node Agent 上验证 `stty size` 从 24x80 变为 30x100；断线重连、过期、跨实例和重放拒绝已有独立证据。

## 集成收口

- E 线终端已改为 WebSocket（网页双向连接）首帧短期令牌，不再把令牌放入网址。
- `lab.release.published` 已由总控事件投递器写入 D 的 `runtime_release_read_model`，并使用 C 发布事件携带的不可变规范快照；真实 MySQL（数据库）测试已覆盖。
