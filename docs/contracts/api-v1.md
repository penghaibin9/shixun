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
