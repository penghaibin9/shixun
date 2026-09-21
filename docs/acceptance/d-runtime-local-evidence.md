# D 线本地真实运行证据（2026-09-21）

环境：Docker Engine 29.7.2（Linux 容器）、MySQL 8.4、固定镜像 `python:3.11-bookworm@sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca`。控制面通过带身份令牌的 Node Agent 操作本机引擎，未向 Web/API 暴露 Docker Socket。

## 单学生闭环

- G4：PASS。控制面真实创建独立内部网络和双容器实例组，并可查询运行状态。
- G5：PASS。浏览器同协议 WebSocket 使用首帧短期令牌进入非 root 学生容器，真实执行 OpenSSL 命令。
- G6：PASS。真实生成密钥、密文、解密结果、签名和报告；5 个检查点由独立、无网络、非 root 临时判定器执行，合计 100 分并写入 MySQL 与事件发件箱。
- 网络：`student → business mysql = DENY`、`student A → student B = DENY`、`student → same-group target/grader = ALLOW`。
- 恢复：重复启动保持同一请求；重建保留 100 分检查点事实；重复销毁成功且最终无残留跃科容器/网络。

执行入口：`scripts/run-runtime-gate.ps1`。

## 单节点容量阶梯

资源请求：每组 2 个容器，共 2 CPU、2048 MB 内存；节点实际总内存约 7774 MB。测试严格按 5 → 10 → 20 个请求递增，未把排队记为启动成功。

| 请求数 | 真实运行 | 排队 | 失败 | 累计耗时 | 节点剩余 CPU | 节点剩余内存 |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 3 | 2 | 0 | 21.056 秒 | 10 | 1629 MB |
| 10 | 3 | 7 | 0 | 37.693 秒 | 10 | 1629 MB |
| 20 | 3 | 17 | 0 | 67.481 秒 | 10 | 1629 MB |

结论：在当前 RSA 配额下，本机单节点实测并发容量为 3 组，限制因素是内存；不能依据原型宣称 50 组。测试结束后运行实例均已销毁，排队请求均已取消，容器与网络清理通过。

执行入口：`scripts/run-runtime-gate.ps1 -GateScript tests/runtime_capacity_gate.py`。

## 尚未通过

- 流量采集器未部署，capture RPC 返回 501；制品存储基地址未配置时下载/打包返回 503。
- E 线当前终端仍把 token 放在查询参数，必须改为首帧；D 不提供不安全兼容。
- C 的 `lab.release.published` 到 D `runtime_release_read_model` 尚需集成事件投递接线。
