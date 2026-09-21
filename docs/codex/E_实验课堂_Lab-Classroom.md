# E｜实验课堂线：Lab Classroom + Teaching Logs

**Codex 窗口：** E  
**工作分支：** `feat/lab-classroom`  
**前置：** P0 Contract；可先按 Contract fixture 做 UI，真实验收必须接 D。  
**主 Gate：** G5 前端链路、G7、采购日志分发。

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

## 1. 负责范围

教师：

- 全班实验运行中心
- 启动/未启动/运行/完成/异常
- 步骤进度/得分
- Terminal 协助
- 日志
- 提醒/重判/延时/解锁/重建/销毁
- 课堂控制
- 实例管理
- 审计/流量日志查看下载与分发

学生：

- 启动实验
- 步骤指导
- Web Terminal
- checkpoint 结果
- 提交
- 日志任务

**E 绝不直接操作 Docker，只调用 D。**

## 2. 原型页面

- `page-lab-live`
- `page-teacher-instances`
- `page-teacher-logs`
- `page-student-lab`
- `page-student-log`

## 3. 采购条款

### 日志集中管理
- 审计日志 tab
- 流量日志 tab
- 查看/下载
- 选日志类型
- 选数量
- 指定学生
- 分发
- 学生收到日志任务

### 实例展示
- 各学生启动情况
- 已启动/未启动/运行/销毁
- 启动时间
- 销毁操作

底层事实来自 D。

## 4. 边界

D 提供 runtime/checkpoint/terminal/log/traffic/rebuild/destroy。  
F 提供平台 audit query。  
E 只拥有教学分发事实：

```text
teaching_log_distribution_task
teaching_log_distribution_item
student_log_assignment
```

不复制 PCAP/审计原文，只引用 artifact/event。

## 5. API

课堂：

```text
GET /api/v1/classroom/lab-releases/{release_id}/summary
GET /api/v1/classroom/lab-releases/{release_id}/students
GET /api/v1/classroom/lab-releases/{release_id}/students/{student_id}

POST /api/v1/classroom/runtime/{id}/remind
POST /api/v1/classroom/runtime/{id}/rejudge
POST /api/v1/classroom/runtime/{id}/extend
POST /api/v1/classroom/runtime/{id}/unlock
POST /api/v1/classroom/runtime/{id}/rebuild
POST /api/v1/classroom/runtime/{id}/destroy

POST /api/v1/classroom/lab-releases/{id}/extend-all
POST /api/v1/classroom/lab-releases/{id}/remind-idle
```

学生：

```text
POST /api/v1/classroom/my/lab-releases/{id}/start
GET  /api/v1/classroom/my/lab-releases/{id}
POST /api/v1/classroom/my/lab-releases/{id}/submit
GET  /api/v1/classroom/my/runtime/{id}/terminal-token
```

日志：

```text
GET  /api/v1/teaching-logs/audit
GET  /api/v1/teaching-logs/traffic
GET  /api/v1/teaching-logs/traffic/{artifact_id}/download

POST /api/v1/teaching-logs/distributions
GET  /api/v1/teaching-logs/distributions
GET  /api/v1/teaching-logs/distributions/{id}

GET  /api/v1/teaching-logs/my-assignments
GET  /api/v1/teaching-logs/my-assignments/{id}/download
```

## 6. 实时

REST 快照 + SSE/WebSocket 增量：

```text
runtime.started
runtime.status.changed
checkpoint.passed
checkpoint.failed
runtime.alert
lab.submitted
runtime.destroyed
```

断线后重连并重新取快照，不能只靠内存流。

## 7. 教师运行中心

KPI：

```text
已启动
已完成
进行中
异常/卡住
未启动
```

列表：

```text
学生
状态
当前步骤
进度
得分
运行时长
实例
最后活动
操作
```

详情 tabs：

```text
步骤
终端
日志
处置
```

所有动作真实调 API，不本地改状态。

## 8. 教师实例管理

顶部汇总真实：

```text
已启动
未启动/等待
运行中
已销毁
异常
```

表增加真实 `启动时间`。  
销毁/重建完成后必须从 D 回读状态。

## 9. 学生实验端

状态机：

```text
未开放
可启动
排队中
启动中
运行中
已提交
已关闭
失败可重试
```

checkpoint/得分从 D 回流，学生不能靠前端 state 伪造。

## 10. Terminal 前端

- 获取 D 短时 token
- WebSocket
- resize
- 断线重连
- Token/权限/实例回收错误提示
- 不把 token 存 localStorage
- 教师协助与学生终端不同 permission scope

教师协助必须审计。

## 11. 日志中心

两个 tab：

### 审计
来自 D runtime logs + F audit（聚合接口）

### 流量
来自 D traffic artifacts

字段：

```text
时间
学生
实验
实例
日志类型
大小/数量
状态
查看
下载
```

## 12. 日志分发

```text
distribution_type: AUDIT / TRAFFIC
source_filter
requested_count
target_student_ids[]
title
instruction
due_at?
```

校验：

- 只能本人任课班
- count 不超可用
- 不可分发别班学生日志
- 仅目标学生可下载
- 下载短期授权 URL
- 分发后学生端有任务

## 13. 权限必测

- 教师 A 看 B 的 release -> deny
- 教师 A 进 B 学生 terminal -> deny
- 学生 A 获取 B token -> deny
- 学生 A 下载 B 日志 -> deny
- 学生 destroy/rebuild -> deny
- 教师高风险动作允许但审计

## 14. Playwright

学生：

`登录 -> 我的实验 -> 启动 -> 等待 -> Terminal -> RSA -> checkpoint -> 提交`

教师：

`登录 -> 运行中心 -> 看到学生启动 -> 步骤/终端/日志 -> 提醒/重判 -> 汇总`

日志：

`流量日志 -> 下载 -> 选 2 条 -> 指定学生 -> 分发 -> 学生登录 -> 任务 -> 下载`

## 15. G7

准备 43 名学生事实，形成：

- 未启动
- 运行中
- 已完成
- 异常

教师页从真实 runtime API 聚合 43 人。

不要为了 G7 在小开发机强行同时起 86 容器；G7 验业务状态与处置，真实并发容量由 D 单独给数据。

## 16. 不可触碰区

禁止：

- docker run/socket
- 改 lab_definition
- 改 gradebook
- 复制 audit/traffic 文件
- 前端本地假改实例状态

## 17. 完成后给我

- commit
- API
- 实时协议
- 日志分发模型
- 学生/教师 Terminal E2E
- 越权测试
- 43 人页面 E2E
- G5 前端链路、G7 PASS/FAIL
- D/F 联调点
