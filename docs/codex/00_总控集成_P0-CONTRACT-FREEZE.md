# 00｜总控集成线：P0-CONTRACT-FREEZE + Integration

**Codex 窗口：** 0  
**工作分支：** `integration`  
**定位：** 架构/契约/共享底座/集成负责人；不承担 A～F 大业务 CRUD。

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

## 1. 目标

先完成 **P0-CONTRACT-FREEZE**，再放行 A～F 并行开发。总控不写大业务 CRUD，只负责共享契约、权限、公共组件、集成和最终 11 步闭环。

成功标准：

1. 六条线不会重复造课程、学生、实验、实例、成绩、文件、审计事实。
2. 数据库 ownership 清楚。
3. API / Event / UserContext / 状态枚举冻结。
4. 公共前端壳、设计 token、自定义控件冻结。
5. 所有分支可独立施工，最后可按固定门禁合入 integration。

## 2. 总控直接 ownership 的原型页面

仅限跨域编排/公共壳：

- `page-teacher-dashboard`
- `page-student-home`
- `page-lifecycle`
- `page-handoff`
- 三角色主导航、顶部栏、公共 Drawer/Modal/Toast/表格/筛选/自定义表单控件

其他页面由 A～F 开发，总控只在集成时接路由、DTO、ReadModel。

## 3. 冻结领域边界

```text
auth / common                 -> 总控
courses/classes/teaching      -> A
resources/question-bank       -> B
lab_definition                -> C
lab_runtime/infrastructure    -> D
lab_classroom/teaching_logs   -> E
grading/analytics/audit       -> F
```

如仓库尚未建结构，建议：

```text
frontend/src/
  app/
  components/common/
  modules/teaching/
  modules/resources/
  modules/lab-designer/
  modules/lab-runtime-admin/
  modules/lab-classroom/
  modules/grading-analytics/

backend/app/
  auth/
  common/
  courses/
  classes/
  teaching/
  resources/
  labs/
  lab_runtime/
  infrastructure/
  lab_classroom/
  teaching_logs/
  grading/
  analytics/
  audit/

node_agent/   # D 独占
```

若已有结构，不强行搬家，只建立等价 ownership。

## 4. 冻结共享 ID

至少：

```text
user_id
teacher_id
student_id
course_id
class_id
class_membership_id
chapter_id
lesson_id

file_id
resource_id
resource_version_id

lab_definition_id
lab_version_id
lab_release_id
checkpoint_id

runtime_request_id
runtime_instance_group_id
runtime_instance_id
checkpoint_result_id

assignment_id
assignment_submission_id
quiz_id
quiz_attempt_id
submission_id

grade_event_id
gradebook_id
audit_event_id
```

硬规则：

- 学生归班唯一事实：`class_membership`
- 课程唯一事实：`course`
- 实验唯一事实：`lab_definition + lab_version`
- 实例唯一事实：`runtime_instance_group + runtime_instance`
- 成绩入口唯一事实：`grade_event`
- 二进制文件统一引用：`file_object`

禁止再造 `course_students / lab_students / resource_students`。

## 5. 共享表（总控 ownership）

如已有等价表则复用：

```text
auth_user
auth_role
auth_permission
auth_user_role

file_object
  file_id
  storage_provider
  bucket
  object_key
  original_name
  mime_type
  size_bytes
  sha256
  created_by
  created_at

domain_event_outbox
  event_id
  event_type
  aggregate_type
  aggregate_id
  actor_user_id
  occurred_at
  payload_json
  idempotency_key
  published_at
```

资源、讲解图、PCAP、日志附件都引用 `file_id`，不重复造文件表。

## 6. 数据库 ownership

```text
A: course_* / class_* / teaching_*
B: resource_* / question_*
C: lab_definition / lab_version / lab_scene_* / lab_dag_* / lab_checkpoint / lab_release*
D: runtime_* / infra_* / checkpoint_result
E: teaching_log_distribution_* / classroom_*（只在确有持久事实时建）
F: grading_* / analytics_* / audit_* / course_archive*
```

迁移规则：

- 各分支只新增自己域的 Alembic revision。
- 禁止修改别人 revision。
- integration 多 head 时由窗口 0 `alembic merge heads`。
- 每次集成都从全新 MySQL 8.4 空库执行 `alembic upgrade head`。

## 7. API Contract v1

统一 `/api/v1`：

```text
/auth/*
/courses/*
/classes/*
/students/*
/attendance/*
/polls/*
/assignments/*
/quizzes/*

/resources/*
/questions/*

/labs/*
/lab-versions/*
/lab-releases/*

/runtime/*
/runtime-instances/*
/infrastructure/*

/classroom/*
/teaching-logs/*

/grading/*
/gradebook/*
/analytics/*
/audit/*
/archives/*
```

统一错误：

```json
{
  "code": "TEACHING.CLASS_FORBIDDEN",
  "message": "无权访问该班级",
  "request_id": "req_xxx",
  "details": {}
}
```

统一分页：

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

冻结 `docs/contracts/openapi-v1.json`，前端类型由 OpenAPI 生成，禁止六条线各自手写同名 DTO。

## 8. UserContext

请求级上下文：

```text
user_id
role
teacher_id?
student_id?
permissions[]
course_ids[]
class_ids[]
```

说明：`course_ids/class_ids` 是请求时解析的数据范围，不要求全部塞 JWT。

权限：

- 教师：本人任课课程/班级及班内学生。
- 学生：本人课程、签到、作业、实验、日志任务、成绩。
- 管理员：基础设施；高风险操作必须审计。
- 原型中的角色切换只作为验收视角，生产环境不得允许普通用户任意切换角色。

## 9. 状态机

至少冻结：

```text
course_status: DRAFT / ACTIVE / ARCHIVED
resource_status: DRAFT / PENDING_REVIEW / PUBLISHED / REJECTED / FROZEN
lab_version_status: DRAFT / VALIDATING / READY / PUBLISHED / RETIRED
lab_release_status: SCHEDULED / OPEN / CLOSED / ARCHIVED
runtime_request_status: QUEUED / SCHEDULING / STARTING / RUNNING / FAILED / CANCELED
runtime_instance_status: CREATED / STARTING / RUNNING / STOPPING / DESTROYED / FAILED
submission_status: DRAFT / SUBMITTED / GRADED / RETURNED
checkpoint_status: PENDING / PASSED / FAILED / ERROR
gradebook_status: CALCULATING / READY / POSTED / LOCKED
archive_status: PRECHECK / READY / ARCHIVED / FAILED
```

## 10. 事件 Contract

统一 envelope：

```json
{
  "event_id": "evt_xxx",
  "event_type": "attendance.completed",
  "aggregate_type": "attendance_task",
  "aggregate_id": "att_xxx",
  "actor_user_id": "usr_xxx",
  "occurred_at": "ISO-8601",
  "idempotency_key": "stable-key",
  "payload": {}
}
```

第一批：

```text
attendance.completed
poll.completed
assignment.submitted
quiz.completed
lab.release.published
lab.instance.started
lab.checkpoint.passed
lab.checkpoint.failed
lab.submitted
lab.instance.failed
lab.instance.destroyed
grade.event.created
gradebook.posted
course.archived
```

业务写入与 outbox 同事务；消费者按 event_id/idempotency_key 幂等。

## 11. 公共前端底座

从最终 HTML 抽取：

- CSS variables / card / badge / table / KPI / progress
- `YkSelect`
- `YkCheck`
- `YkRadio`
- `YkTabs`
- `YkModal`
- `YkDrawer`
- `YkToast`
- `YkDataTable`
- `YkPageHeader`

要求键盘可操作、ARIA 正确；A～F 禁止复制自己的下拉/复选版本。

## 12. 页面 ownership

```text
总控：
teacher-dashboard / student-home / lifecycle / handoff / app-shell

A：
courses / attendance-management / teacher-assignments /
student-course / student-attendance / student-quiz

B：
resources / course-blueprint / course-theory / course-lab-lessons /
course-ppt / course-video / course-questions /
course-procurement / course-resource-audit / course-delivery

C：
labs / lab-templates / course-knowledge / lab-builder

D：
admin-overview / admin-nodes / admin-images / admin-scheduler /
admin-network / admin-instances / admin-alerts / admin-recovery

E：
lab-live / teacher-instances / teacher-logs /
student-lab / student-log

F：
teacher-grades / analytics / archive / student-score / admin-audit
```

## 13. 8 道总 Gate

```text
G1 课程 -> 班级 -> XLSX 导学生
G2 教师发布签到 -> 学生真实签到
G3 RSA 实验定义完整、版本化、预检通过
G4 学生真实启动 Docker
G5 浏览器真实 Web Terminal
G6 RSA 真实自动判分
G7 教师实时查看 43 人状态并处理异常
G8 成绩 -> 学情 -> 课程归档
```

## 14. 合并门禁

并行开发，合并按：

```text
A -> B -> C -> D -> E -> F -> Integration E2E
```

每次：

1. 空库 migration
2. OpenAPI contract diff
3. pytest
4. frontend build/unit
5. 已具备的 Playwright
6. 越权测试
7. 审计写入检查
8. D/E 后增加 Linux Docker runtime gate

失败不得进入下一条合并。

## 15. P0 必须实际交付

```text
docs/architecture/domain-boundaries.md
docs/architecture/database-ownership.md
docs/contracts/api-v1.md
docs/contracts/events-v1.md
docs/contracts/openapi-v1.json
docs/security/permission-context.md
docs/parallel/workstream-a.md
docs/parallel/workstream-b.md
docs/parallel/workstream-c.md
docs/parallel/workstream-d.md
docs/parallel/workstream-e.md
docs/parallel/workstream-f.md
docs/acceptance/gates.md
```

并落地：

- UserContext middleware/dependency
- common error envelope
- file_object abstraction
- event outbox 基础
- app shell/routes/common components
- 基础 MySQL migration
- 最小 contract tests

## 16. 完成后只给我

1. P0 commit hash
2. 新增/修改文件
3. migration heads
4. OpenAPI 校验
5. 基础测试
6. A～F 是否可同时开工
7. 仍阻塞的唯一原因（如有）
8. 不要继续替 A～F 写大业务
