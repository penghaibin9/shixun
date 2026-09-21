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
