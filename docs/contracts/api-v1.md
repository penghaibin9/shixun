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
GET    /api/v1/classes/{class_id}/students/{student_id}/learning-summary
```

成员列表必须服务端分页，支持姓名/学号搜索、账号状态过滤及学号/姓名排序。学习汇总由总控聚合 A 的签到/作业/测验、E 的实验状态、F 的总评/风险 ReadModel；未接入的跨域字段返回 `null` 和 `data_status: "PENDING"`，A 不得跨域直连表或自行计算实验成绩与风险。

## B 课程资源接口

已落地 `/resources` 与 `/questions` 全部冻结接口。资源查询支持 `course_id`、`status`、`name`、`resource_type` 三维组合过滤；写入须分别具备 `resources:write`、`resources:review`、`resources:freeze` 权限。教师课程范围来自 `UserContext`，学生只能读取 `PUBLISHED`（已发布）或 `FROZEN`（已冻结）资源。

资源版本只新增不覆盖，文件必须引用公共 `file_object.file_id`，且请求的 SHA256（文件校验值）必须与文件对象一致。发布顺序为 `DRAFT（草稿） -> PENDING_REVIEW（待审核） -> PUBLISHED（已发布） -> FROZEN（已冻结）`；制作人与审核人必须不同。

完整性审计按 37 个理论课时的 PPT（演示文稿）/视频/题型/审核，以及 12 个实验课时的介绍/文件包/视频/题型实时计算 196 个检查点。`blocking > 0` 时 `POST /api/v1/resources/delivery/freeze` 固定返回 `RESOURCE.DELIVERY_BLOCKED`，清单可导出 JSON（结构化数据）和 XLSX（电子表格）。

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
