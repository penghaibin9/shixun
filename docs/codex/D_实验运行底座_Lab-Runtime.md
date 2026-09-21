# D｜实验运行底座线：Real Lab Runtime & Infrastructure

**Codex 窗口：** D  
**工作分支：** `feat/lab-runtime`  
**前置：** P0 Contract；C 的 RSA schema 至少已确定。  
**主 Gate：** G4、G5、G6 的底层能力。

## 共同执行纪律

- 唯一产品/交互基线：`跃科网络空间安全实训平台_采购文件完善版_FINAL.html`
- 采购验收依据：湖南工商大学《网络空间安全实训平台项目采购文件》（HUTB[2026]062号）
- 开工先扫描当前仓库、已有 migrations/API/模型/组件/测试；能复用的一律复用，禁止重新造第二套同名业务事实。
- 原型负责页面结构、字段、按钮、三角色和 11 步闭环；正式工程必须把 JS 写死数据替换为真实 API、真实 MySQL、真实文件、真实 Docker/日志/成绩事实。
- 前端不得重新设计一套 UI。尽量忠实最终 HTML；`yk-select / yk-check / yk-radio` 要落成可复用 Vue 组件，不出现浏览器默认控件外观。
- 权威事实库使用 MySQL 8.4 / InnoDB。Redis 如使用，只能做锁、Pub/Sub、Terminal session 等瞬时能力，不能成为课程、实例、成绩、审计事实源。
- 页面数据路径固定：`Vue -> API -> Service -> Repository -> MySQL`。
- 每个写接口必须有鉴权、数据范围、输入校验、幂等/防重复（适用时）、审计事件和明确错误码。
- 各施工线只改自己的 ownership；跨域通过冻结 Contract 调用，禁止“顺手重构”别人模块。
- 除总控 P0 外，不要只交分析报告；必须实际修改代码、迁移、测试并形成可运行提交。
- 测试至少覆盖 pytest、真实 MySQL 集成、前端 build、关键前端测试、对应 Playwright；涉及 Docker 的 Gate 必须在 Linux Docker 环境真实跑。

---

## 1. 核心目标

这条线不是模拟。

> 学生点击启动后，Linux 计算节点真实创建隔离 Docker 网络/容器，浏览器真实 Terminal，RSA 命令真实执行，grader 真实判定，实例真实销毁/重建。

第一阶段只跑 **RSA 单学生最小闭环**，再扩并发。

## 2. 原型页面

- `page-admin-overview`
- `page-admin-nodes`
- `page-admin-images`
- `page-admin-scheduler`
- `page-admin-network`
- `page-admin-instances`
- `page-admin-alerts`
- `page-admin-recovery`

E 的教师/学生页只调用 D API。

## 3. 采购 ownership

实验管理实例能力：

- 实例状态
- 实例销毁
- 各学生实例启动事实

并承担交钥匙项目中的真实虚拟化实训环境底座。

## 4. 运行架构

禁止把 Docker Socket 暴露给 Web/API：

```text
Browser
 -> Control API (FastAPI)
 -> Runtime Service/Scheduler
 -> authenticated Node Agent
 -> local Docker Engine
```

Terminal：

```text
Browser WebSocket
 -> Control Plane 短期 token
 -> Node Agent
 -> docker exec bridge
 -> student container
```

第一阶段 control/agent 可同机，但代码边界保持。

## 5. 数据 ownership

```text
infra_node
infra_node_heartbeat
infra_image
infra_image_validation

runtime_request
runtime_queue
runtime_instance_group
runtime_instance
runtime_container
runtime_network
runtime_event
runtime_resource_usage
runtime_terminal_session
runtime_artifact

checkpoint_result
```

checkpoint_result 属 D；F 消费生成 grade_event。

## 6. Node Agent

受控 RPC：

```text
GET  /health
GET  /capacity
POST /images/pull
POST /runtime-groups
GET  /runtime-groups/{id}
POST /runtime-groups/{id}/exec
POST /runtime-groups/{id}/destroy
POST /runtime-groups/{id}/capture/start
POST /runtime-groups/{id}/capture/stop
```

硬约束：

- 只接受 Control Plane 身份
- 不提供任意 Docker API passthrough
- container label 带 runtime group id
- 只允许白名单 image digest
- CPU/内存/PID 限制
- 禁 privileged
- 禁 Docker socket mount
- mount 只允许批准路径
- 超时回收
- 启动后 reconcile 孤儿容器/网络

## 7. Scheduler

输入：

```text
lab_version 资源需求
image digest
cpu/memory
network policy
node capacity
image cache
health
```

必须记录：

```text
node_id
score
reason
scheduled_at
```

支持 Ready、暂停调度、权重、缓存优先、失败换节点、幂等 start、queue。

## 8. Runtime API

```text
POST /api/v1/runtime/start
GET  /api/v1/runtime/requests/{id}

GET  /api/v1/runtime-instances/{id}
POST /api/v1/runtime-instances/{id}/destroy
POST /api/v1/runtime-instances/{id}/rebuild
POST /api/v1/runtime-instances/{id}/extend
POST /api/v1/runtime-instances/{id}/rejudge

GET  /api/v1/runtime-instances/{id}/logs
GET  /api/v1/runtime-instances/{id}/traffic-artifacts
POST /api/v1/runtime-instances/{id}/terminal-token

GET  /api/v1/infrastructure/nodes
GET  /api/v1/infrastructure/images
GET  /api/v1/infrastructure/queue
```

start 必须支持 `Idempotency-Key`。

## 9. 网络隔离

默认：

- 每学生/实例组独立网络
- 学生 A 不能访问学生 B
- 实验网不能访问业务 MySQL、管理网、Docker daemon
- 外网按实验 allowlist
- grader 端口单独放行
- 销毁回收网络

自动验证：

```text
student -> business mysql : DENY
student A -> student B    : DENY
student -> grader allowed : ALLOW
```

## 10. 镜像

```text
name
tag
digest
size
scan_status
startup_check_status
teaching_validation_status
enabled
```

C 发布 lab_version 必须固定 digest，不准 `latest` 漂移。

## 11. RSA 真闭环

真实命令：

```bash
openssl genpkey
openssl pkey
openssl pkeyutl
openssl dgst
sha256sum
```

真实产物：

```text
private.pem
public.pem
cipher.bin
plain.out
signature.bin
report.*
```

真实判定：

1. keypair：文件+格式
2. encrypt：cipher.bin 非空
3. decrypt：plain.out 与 source.txt SHA256 相等
4. sign：验签成功
5. report：文件存在

grader：

- 非 root
- 超时
- 输出限制
- 默认无外网
- 不在 Control Plane 主进程执行
- 结果入 checkpoint_result
- 发事件

## 12. Web Terminal

token：

- 短期
- scope 到 user_id + runtime_instance_id
- 服务端再次校验 ownership
- 不长期放 URL/localStorage

WebSocket：

- stdin/stdout
- resize
- idle timeout
- session audit
- 断线不销毁实例

只能进指定 student container，不能进宿主机。

## 13. 日志/流量

为 E/F 产生：

### 审计运行日志
start/stop/exec/checkpoint/rebuild/destroy/node/error

### 流量 artifact
采购需要流量日志查看/下载/分发：

```text
instance_id
student_id
capture start/end
file_id
sha256
size
```

E 负责分发，F 负责平台审计。

## 14. 恢复

- heartbeat timeout
- request retry
- start fail rollback
- rebuild 保留 checkpoint/得分
- destroy 幂等
- zombie cleanup
- service restart reconcile
- orphan network/container cleanup

## 15. 管理员前端

把原型所有百分比/容器数接真实 API：

- 节点
- 镜像
- 队列
- 调度决策
- 网络验证
- 实例
- 告警
- 恢复记录

## 16. 安全硬约束

禁止：

- Docker unauth TCP
- privileged
- host network/PID/IPC
- Docker socket
- 可写 hostPath
- 未固定 digest
- Terminal 未二次鉴权

高风险动作发 audit event。

## 17. 测试顺序

### D1 单机 Docker
`start -> network -> 2 containers -> terminal -> RSA -> checkpoints -> destroy`

### D2 故障
重复 start、镜像缺失、agent timeout、start fail、token 越权、destroy twice、rebuild。

### D3 网络
三条隔离 Gate。

### D4 并发
5 -> 10 -> 20 逐步压测，记录 CPU/内存/启动耗时/失败率后再定容量，禁止凭原型宣称 50 组。

## 18. Gate

### G4
真实创建实例组并可查询状态。

### G5 底层
真实 WebSocket Terminal 进入容器。

### G6 底层
RSA 5 checkpoint 真判分，100 分，checkpoint_result 入库并发事件。

## 19. 不可触碰区

禁止改课程/班级/资源内容/成绩公式/E 业务 UI；禁止 mock 作为 Gate 证据。

## 20. 完成后给我

- commit
- node_agent 部署
- migration
- RSA 真运行证据
- Terminal E2E
- 隔离测试
- destroy/rebuild/recovery
- G4/G5/G6 底层 PASS/FAIL
- 单节点实测容量
