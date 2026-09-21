# AGENTS.md

## 1. 项目身份

项目：跃科网络空间安全实训平台  
当前阶段：从最终 HTML 原型进入正式工程开发。  

项目根目录中的以下文件是长期基线：

- `docs/UI/跃科网络空间安全实训平台_采购文件完善版v6.html`
  - UI、菜单、三角色、页面结构、字段、按钮和 11 步教学闭环的产品/交互基线。
- `docs/procurement/湖南工商大学_网络空间安全实训平台_采购文件.doc`
  - 本项目采购技术参数和验收需求依据。
- `docs/codex/`
  - 00 + A～F 共 7 条施工线的任务书。用户指定某条施工线时，必须读取对应任务书并以其为本窗口任务范围。

不要重新设计另一套产品，不要把原型删减成“简单 Demo”。

---

## 2. 开工规则

每次施工都先做这 6 件事：

1. 读取本文件 `AGENTS.md`。
2. 读取用户指定的 `docs/codex/*.md` 任务书。
3. 扫描当前仓库、已有代码、migration、API、组件、测试。
4. 能复用的一律复用；禁止重新造第二套课程、学生、实验、实例、成绩、资源或审计事实。
5. 给出极简施工计划后直接改代码，不要只交分析文档。
6. 完成后运行本任务书要求的最小测试，修到通过或明确给出真实阻断证据。

如果任务书与本文件冲突：
- 用户当前明确指令优先；
- 其次是更具体的任务书；
- 本文件负责长期公共规则。

---

## 3. 固定技术路线

除非现有仓库已经有成熟等价实现，否则统一采用：

### 前端
- Vue 3
- TypeScript
- Vite
- Pinia
- Vue Router

### 后端
- Python
- FastAPI
- SQLAlchemy 2.x
- Alembic

### 数据
- MySQL 8.4 / InnoDB 为正式事实库
- Redis 只用于锁、队列、Pub/Sub、短时 session 等瞬时能力
- 不允许用 Redis 代替正式成绩、实例、资源或审计事实

### 实验运行
- Linux 计算节点
- Docker
- 独立 Node Agent
- WebSocket Web Terminal
- 受限 grader

真实验收不得用 SQLite、前端假数据或 mock Docker 代替 MySQL/Docker 主链。

---

## 4. 产品硬约束

必须长期保留：

- 教师 / 学生 / 管理员三角色。
- 11 步教学闭环：
  `创建课程 -> 建班/导学生 -> 备课 -> 签到 -> 理论教学 -> 发布实验 -> 学生实验 -> 作业测验 -> 自动成绩 -> 学情分析 -> 课程归档`
- 理论课程固定按当前最终原型实现 **37 课时**，满足采购“不少于 36 课时”。
- 实验课程固定 **12 课时**。
- 8 类采购核心实验必须有明确映射。
- 所有课程、班级、学生、实验定义、实验版本、运行实例、成绩、资源版本、审计事件必须有唯一事实源。
- 所有重要导入导出使用 `.xlsx`，必须有模板、校验、错误行反馈和权限控制。

---

## 5. 六条业务线边界

### A teaching-core
负责：
- course / class / class_membership
- 签到
- 投票
- 作业
- 测验

禁止：
- Docker
- runtime
- grader
- 正式 gradebook

### B course-resources
负责：
- 37 理论 / 12 实验课时资源
- PPT
- 视频
- 题库
- 实验文件
- 资源版本/审核/交付

禁止：
- 自建课程/学生事实
- Docker
- 正式成绩

### C lab-designer
负责：
- 实验模板
- 知识点讲解图
- 拓扑/网络/设备
- 镜像绑定引用
- DAG/checkpoint
- 实验版本/发布配置

原则：
**C 定义实验，不运行实验。**

### D lab-runtime
负责：
- Node Agent
- Docker
- 调度
- 实例
- 网络隔离
- Web Terminal 底座
- grader/checkpoint_result
- 镜像与基础设施

原则：
**只有 D 可以直接操作 Docker。**

### E lab-classroom
负责：
- 教师实验运行中心
- 学生实验页面
- 43 人状态
- 教师处置
- 教学日志查看/下载/分发
- Terminal 前端

原则：
**E 只能调用 D，禁止自己 docker run。**

### F grading-analytics-audit
负责：
- grade_event
- gradebook
- 学情
- 排行/分布
- 归档
- audit_event

原则：
**F 消费事实，不重新制造签到、作业、实验事实。**

---

## 6. 页面 ownership

总控：
- teacher-dashboard
- student-home
- lifecycle
- handoff
- app-shell

A：
- courses
- attendance-management
- teacher-assignments
- student-course
- student-attendance
- student-quiz

B：
- resources
- course-blueprint
- course-theory
- course-lab-lessons
- course-ppt
- course-video
- course-questions
- course-procurement
- course-resource-audit
- course-delivery

C：
- labs
- lab-templates
- course-knowledge
- lab-builder

D：
- admin-overview
- admin-nodes
- admin-images
- admin-scheduler
- admin-network
- admin-instances
- admin-alerts
- admin-recovery

E：
- lab-live
- teacher-instances
- teacher-logs
- student-lab
- student-log

F：
- teacher-grades
- analytics
- archive
- student-score
- admin-audit

未经总控契约调整，不要跨线重构别人页面。

---

## 7. 前端规则

- 最终 HTML 是视觉/信息架构基线，不重新套模板。
- 抽公共组件，不复制 6 套同类组件。
- 原型中的 `yk-select / yk-check / yk-radio` 应实现为公共 Vue 组件。
- 可以用隐藏原生 input 提升无障碍，但不得显示浏览器默认 checkbox/radio/select 外观。
- 所有正式页面数据来自 API，不允许把原型 JS 写死数据继续当正式业务数据。
- 加载、空状态、错误状态、无权限状态都要明确。
- 重要 destructive 操作必须二次确认。

---

## 8. 后端与数据库规则

固定调用链：

`Vue -> API -> Service -> Repository -> MySQL`

要求：

- API 不直接堆 SQL。
- Repository 不承载复杂业务规则。
- Service 负责权限、状态机、事务和业务校验。
- Alembic migration 只能新增，不要随意修改已合并历史 migration。
- 所有外键/唯一键/必要索引必须真实存在。
- 正式验收使用 MySQL 8.4，不以 SQLite 通过代替。
- 跨域只能通过冻结 ID、API、Event Contract 协作。

---

## 9. 权限与审计

统一使用 UserContext / permission / data scope，不允许各模块散落：

`if role == "teacher"` 之类临时越权逻辑。

必须保证：

- 教师只能访问本人任课课程/班级及其学生。
- 学生只能访问本人数据、本人实例、本人日志、本人作业、本人分数。
- 管理员高风险动作必须审计。
- 教师协助学生 Terminal、重建/销毁实例、人工改分、资源冻结、课程归档必须审计。
- 审计事件不得由普通业务接口修改或删除。

---

## 10. 实验安全底线

禁止：

- Web/API 直接暴露 Docker Socket。
- privileged 容器。
- 宿主机 Docker Socket mount。
- 默认 host network / host PID / host IPC。
- 未固定 digest 的生产实验镜像。
- 控制平面直接执行教师输入的任意判定脚本。
- 学生实验网络访问业务 MySQL 或管理网络。
- 学生 A 默认访问学生 B 实例。
- Web Terminal 进入宿主机 shell。

grader 必须受限、超时、资源限制并记录结果。

---

## 11. Git / 并行规则

本项目允许不使用 GitHub，但**必须使用本地 Git**。

长期分支约定：

```text
main
integration
feat/teaching-core
feat/course-resources
feat/lab-designer
feat/lab-runtime
feat/lab-classroom
feat/grading-analytics
```

并行开发必须使用 Codex Worktree 或独立 Git worktree，禁止 7 个窗口同时在同一个工作目录直接改。

每条线只修改自己的 ownership。合并冲突交给总控窗口处理。

---

## 12. 8 道总验收 Gate

```text
G1 课程 -> 班级 -> XLSX 导学生
G2 教师发布签到 -> 学生真实签到
G3 RSA 实验定义完整、版本化
G4 学生真实启动 Docker
G5 浏览器真实 Web Terminal
G6 RSA 真实自动判分
G7 教师实时查看 43 人实验状态并处置异常
G8 成绩 -> 学情 -> 课程归档
```

页面数量不是完成标准，Gate 才是。

---

## 13. 完成定义

任何施工任务完成前，至少做到：

1. 真实代码已修改。
2. migration 已提供并可从空库升级。
3. 后端相关 pytest 通过。
4. 真实 MySQL 集成测试通过。
5. 前端 build 通过。
6. 对应 Playwright 主链通过。
7. 涉及 Docker 的任务有真实 Linux Docker 证据。
8. 权限/越权测试通过。
9. 审计事件可查。
10. 工作区只保留本任务应有改动。

如果环境确实无法完成某项验收：
- 不得伪造 PASS；
- 给出实际命令、实际错误和唯一阻断原因；
- 其余可完成部分继续完成。

---

## 14. Codex 最终回复格式

每次施工完成后只需要给用户：

1. 一句话判断：PASS / PARTIAL / BLOCKED。
2. 本次真正完成的代码。
3. 改动文件/迁移/接口。
4. 测试命令和结果。
5. 对应 Gate 状态。
6. 仍有的真实阻断。
7. 下一步唯一动作。

不要用大段空泛总结替代代码施工。
