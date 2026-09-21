# API（应用程序接口）契约 v1

统一前缀：`/api/v1`。资源路由归属如下：

| 路由前缀 | 所有者 |
|---|---|
| `/auth` | 总控 |
| `/courses`、`/classes`、`/students`、`/attendance`、`/polls`、`/assignments`、`/quizzes` | A |
| `/resources`、`/questions` | B |
| `/labs`、`/lab-versions`、`/lab-releases` | C |
| `/runtime`、`/runtime-instances`、`/infrastructure` | D |
| `/classroom`、`/teaching-logs` | E |
| `/grading`、`/gradebook`、`/analytics`、`/audit`、`/archives` | F |

成功列表统一为 `items`、`page`、`page_size`、`total`；错误统一为 `code`、`message`、`request_id`、`details`。所有写接口必须鉴权、做数据范围校验、参数校验、适用时使用幂等键，并在同一事务写审计事件和事件发件箱。

已落地的总控接口：`GET /api/v1/auth/context`，从身份提供方解析请求用户、角色、权限及课程/班级范围。生产身份由认证中间件注入；开发环境请求头仅用于契约测试，不能作为生产认证方案。

## 教师学生管理

A 负责以下接口，班级成员唯一事实均为 `class_membership`：

```text
GET    /api/v1/classes/{class_id}/members
GET    /api/v1/classes/{class_id}/members/{student_id}
POST   /api/v1/classes/{class_id}/members
POST   /api/v1/classes/{class_id}/members/import
DELETE /api/v1/classes/{class_id}/members/{student_id}
GET    /api/v1/classes/{class_id}/members/import-template
GET    /api/v1/classes/{class_id}/members/export.xlsx
POST   /api/v1/classes/{class_id}/roster/freeze
GET    /api/v1/classes/{class_id}/students/{student_id}/learning-summary
```

成员列表必须服务端分页，支持姓名/学号搜索、账号状态过滤及学号/姓名排序。名单冻结生成按学号排序的 SHA256（文件校验值）快照并发布 `course.roster.frozen`，冻结后加入、移出和导入固定返回 `CLASS.ROSTER_FROZEN`。学习汇总由总控聚合 A 的签到/作业/测验、E 的实验状态、F 的总评/风险 ReadModel；未接入的跨域字段返回 `null` 和 `data_status: "PENDING"`，A 不得跨域直连表或自行计算实验成绩与风险。

## 总控事件投递接口

`POST /api/v1/integration/outbox/dispatch` 仅允许 `service_` 前缀的管理员服务身份并要求 `integration:dispatch` 权限。投递器从 `domain_event_outbox` 读取未发布事件：D 运行事件写入 E 课堂投影并送入 F 成绩事实，A/B 冻结事件送入 F 归档证据，C 的 `lab.release.published` 携带不可变实验规范快照写入 D 发布上下文。任一目标失败时事件保持未发布，可安全重试；各消费者按 `event_id` 幂等。

## B 课程资源接口

已落地 `/resources` 与 `/questions` 全部冻结接口。资源查询支持 `course_id`、`status`、`name`、`resource_type` 三维组合过滤；写入须分别具备 `resources:write`、`resources:review`、`resources:freeze` 权限。教师课程范围来自 `UserContext`，学生只能读取 `PUBLISHED`（已发布）或 `FROZEN`（已冻结）资源。

资源版本只新增不覆盖，文件必须引用公共 `file_object.file_id`，且请求的 SHA256（文件校验值）必须与文件对象一致。发布顺序为 `DRAFT（草稿） -> PENDING_REVIEW（待审核） -> PUBLISHED（已发布） -> FROZEN（已冻结）`；制作人与审核人必须不同。

完整性审计按 37 个理论课时的 PPT（演示文稿）/视频/题型/审核，以及 12 个实验课时的介绍/文件包/视频/题型实时计算 196 个检查点。`blocking > 0` 时 `POST /api/v1/resources/delivery/freeze` 固定返回 `RESOURCE.DELIVERY_BLOCKED`，清单可导出 JSON（结构化数据）和 XLSX（电子表格）。

## C 线实验定义接口

已落地：

- `GET/POST /api/v1/labs`、`GET /api/v1/labs/{id}`
- `POST /api/v1/labs/{id}/versions`：从现有版本克隆新的 `DRAFT`（草稿）版本
- `GET/PATCH /api/v1/lab-versions/{id}`：`PUBLISHED`（已发布）版本禁止修改
- `POST /api/v1/lab-versions/{id}/validate`、`POST /api/v1/lab-versions/{id}/publish`
- `GET /api/v1/lab-versions/{id}/export.json`
- `GET/POST /api/v1/lab-templates`
- `GET/POST/PATCH /api/v1/lab-knowledge`
- `GET /api/v1/lab-knowledge/{id}/diagrams/{diagram_id}/download`
- `POST /api/v1/lab-releases` 及其 `preflight`（预检）、`teacher-preview`（教师预演）、`publish`（发布）动作

所有写接口要求 `X-Idempotency-Key`（幂等键）；权限使用 `labs.read`、`labs.write`、`labs.publish`、`labs.knowledge.write`。课程和班级必须分别位于 `UserContext.course_ids` 与 `UserContext.class_ids`。实验定义 JSON（数据文本）遵循 `lab-definition-v1.schema.json`；C 线只保存定义，教师预演仅调用 D 线，D 不可用时返回 `LAB.RUNTIME_PROVIDER_UNAVAILABLE`（运行服务不可用）。

## F 成绩、学情、归档与审计接口

F 域只消费 A/D/E 发布的冻结事件，不提供签到、作业、测验、实验提交或班级成员写接口。`POST /api/v1/grading/events/consume` 按上游 `event_id` 幂等，同一事件重复投递不会重复计分。

默认成绩规则为签到 10%、作业 20%、测验 20%、实验 40%、互动 10%；规则版本发布后不可覆盖。`POST /api/v1/grading/courses/{course_id}/recalculate` 仅使用 `grade_event` 计算，`POSTED（已入账）` 或 `LOCKED（已锁定）` 成绩不可静默修改。

新增 `GET /api/v1/analytics/courses/{course_id}/learning-summary?class_id={class_id}` 作为教师/学生管理 CR（变更请求）的只读模型，仅返回成绩、风险和学情摘要。成绩册、追溯、学情、风险和导出接口同样强制显式 `class_id`，并同时校验课程/班级数据范围，禁止按课程猜测“最新班级”。上游班级成员、完整教学事实或成绩入账缺失时返回 `PENDING（待处理）` 或 `PARTIAL（部分数据）`；学生响应不包含其他学生标识。

`POST /api/v1/grading/events/consume` 与 `POST /api/v1/audit/events/ingest` 仅接受具备专用权限的内部服务身份，普通教师或浏览器身份不可调用。`lab.submitted` 必须同时携带 `source_id`（提交事实标识）与 `lab_release_id`（实验发布标识）；前者用于追溯，后者用于实验维度聚合。

归档预检要求班级名单冻结事实、已入账成绩、可追溯成绩事件、实验判分引用和 B 资源冻结事实全部存在。冻结生成的成绩册与学情 XLSX（电子表格）复用 P0 `file_object`（文件对象）登记摘要、大小和下载位置，`course_archive_artifact.file_id` 使用真实外键关联；实验日志只保存上游证据引用，不复制 D/E 事实。跨域高风险动作通过受限的 `POST /api/v1/audit/events/ingest` 幂等追加；审计业务接口只提供查询和 XLSX（电子表格）/CSV（逗号分隔文件）导出，不提供修改或删除。

## 共享 ID（标识符）

冻结：`user_id`、`teacher_id`、`student_id`、`course_id`、`class_id`、`class_membership_id`、`chapter_id`、`lesson_id`、`file_id`、`resource_id`、`resource_version_id`、`lab_definition_id`、`lab_version_id`、`lab_release_id`、`checkpoint_id`、`runtime_request_id`、`runtime_instance_group_id`、`runtime_instance_id`、`checkpoint_result_id`、`assignment_id`、`assignment_submission_id`、`quiz_id`、`quiz_attempt_id`、`submission_id`、`grade_event_id`、`gradebook_id`、`audit_event_id`。

## 状态机

| 名称 | 冻结取值 |
|---|---|
| 课程 | `DRAFT`、`ACTIVE`、`ARCHIVED` |
| 资源 | `DRAFT`、`PENDING_REVIEW`、`PUBLISHED`、`REJECTED`、`FROZEN` |
| 实验版本 | `DRAFT`、`VALIDATING`、`READY`、`PUBLISHED`、`RETIRED` |
| 实验发布 | `SCHEDULED`、`OPEN`、`CLOSED`、`ARCHIVED` |
| 运行请求 | `QUEUED`、`SCHEDULING`、`STARTING`、`RUNNING`、`FAILED`、`CANCELED` |
| 运行实例 | `CREATED`、`STARTING`、`RUNNING`、`STOPPING`、`DESTROYED`、`FAILED` |
| 提交 | `DRAFT`、`SUBMITTED`、`GRADED`、`RETURNED` |
| 检查点 | `PENDING`、`PASSED`、`FAILED`、`ERROR` |
| 成绩册 | `CALCULATING`、`READY`、`POSTED`、`LOCKED` |
| 归档 | `PRECHECK`、`READY`、`ARCHIVED`、`FAILED` |
