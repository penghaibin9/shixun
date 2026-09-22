# API（应用程序接口）契约 v1

统一前缀：`/api/v1`。资源路由归属如下：

| 路由前缀 | 所有者 |
|---|---|
| `/auth` | 总控 |
| `/courses`、`/classes`、`/students`、`/attendance`、`/polls`、`/assignments`、`/quizzes` | A |
| `/resources`、`/questions` | B |
| `/labs`、`/lab-versions`、`/lab-releases` | C |
| `/runtime`、`/runtime-instances`、`/infrastructure`、`/artifact-storage` | D |
| `/classroom`、`/teaching-logs` | E |
| `/grading`、`/gradebook`、`/analytics`、`/audit`、`/archives` | F |

成功列表统一为 `items`、`page`、`page_size`、`total`；错误统一为 `code`、`message`、`request_id`、`details`。所有写接口必须鉴权、做数据范围校验、参数校验、适用时使用幂等键，并在同一事务写审计事件和事件发件箱。

`docs/contracts/openapi-v1.json` 由 `scripts/freeze_openapi.py` 从当前 FastAPI（后端接口框架）真实路由生成，契约测试要求其与运行时规范逐字段一致。前端执行 `npm run contracts:generate` 生成 `frontend/src/app/api-contract.generated.ts`，共享错误信封和用户上下文类型必须直接引用生成结果；禁止手工维护第二份同名共享 DTO（数据传输对象）。

已落地的总控接口：`GET /api/v1/auth/context`，从身份提供方解析请求用户、角色、权限及课程/班级范围。生产身份由认证中间件注入；开发环境请求头仅用于契约测试，不能作为生产认证方案。

## 课程与课时权威目录

A 的 `course`、`course_chapter`、`course_lesson` 是全平台课程、章节和课时的唯一事实来源。创建课程时，A 在同一事务建立 8 章、37 个理论课时和 12 个实验课时；`GET /api/v1/courses/{course_id}/lessons` 按章节与课时顺序返回该课程的权威目录。`course_lesson.lesson_code` 在课程内唯一，所有教学任务、资源和题目映射必须同时匹配 `course_id` 与 `lesson_id`，跨课程引用固定拒绝。

B 的 `lesson_resource` 仅保存实验介绍、文件包、视频和实验定义等资源扩展，不拥有课时标题、编号、类型与章节。B 的蓝图、就绪度、交付清单、题库模板和审核队列均从 A 的权威目录读取；迁移 `20260922_0013` 将历史 49 个课时回填至 A 并建立课程/课时外键，迁移 `20260922_0014` 在一致性预检后物理删除 B 中重复的课时事实字段。

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

## D/E 日志分发下载授权

学生通过 E 的 `GET /api/v1/teaching-logs/my-assignments/{assignment_id}/download` 请求本人日志任务。E 校验分配事实、学生身份、课程、班级和实验发布后，向 D 的内部接口 `POST /api/v1/runtime/log-artifacts/distribution-bundle-url` 提交最长 60 秒的签名授权。授权精确绑定 `assignment_id`、`distribution_id`、日志类型、学生、课程、班级、实验发布、引用集合和随机数；D 重新验证签名、有效期、学生范围以及每个运行日志源事实后，才换取独立的短期存储能力。

该授权只使用 `runtime.distributed-artifact.download` 窄权限，不改变普通制品接口的实例所有权规则。跨学生、跨班级、跨实验发布、篡改引用和过期授权固定拒绝；同一授权重放返回相同能力并只追加一条 `runtime.artifact.distribution_download_authorized` 审计事件。E 与 D 共享的分发签名密钥和 D 与制品服务共享的存储签名密钥必须分离。

D 签发的存储能力固定使用 `issuer=lab-runtime`、`audience=artifact-storage`，绑定下载账号、授权类型、任务或下载包标识、完整引用集合、每项 `file_id + sha256 + size_bytes`、随机数及不超过 120 秒的签发/过期时间。`GET /api/v1/artifact-storage/bundles/{assignment_id}` 消费该能力并返回真实 ZIP（压缩包）；下载时重新查询 D 源事实和公共 `file_object`（文件对象），逐项流式计算大小与 SHA256（文件校验值），任一登记缺失、元数据变化、文件缺失、摘要错误或路径越界即拒绝整包。同一能力重复下载只追加一条下载审计事件。审计日志分发按运行事件事实生成规范化 JSON（结构化数据）条目，不伪造 `file_object`。

普通 `POST /api/v1/runtime/log-artifacts/{artifact_id}/download-url` 与 `POST /api/v1/runtime/log-artifacts/bundle-url` 使用同一存储端点和真实 ZIP（压缩包），能力绑定当前账号和精确引用集；下载端再次执行原有实例所有权校验，不能借普通下载跨学生或跨班级读取。

流量采集落盘/导入契约：Node Agent（节点代理）只返回受控采集结果，控制面必须把文件导入 `YUEKE_RUNTIME_ARTIFACT_DIR` 指定的根目录（默认 `backend/var/runtime_artifacts`）并登记 `file_object`。登记固定为 `storage_provider=local`、`bucket=runtime-artifacts`，`object_key` 使用该根目录内的相对对象键（推荐直接使用 `file_id`）或解析后仍位于根目录内的绝对路径；`runtime_artifact.file_id/sha256/size_bytes` 必须逐项等于文件对象登记值。下载端不接受任意外部 URL（网址）、其他存储桶、符号链接解析后的越界路径或未登记文件。

## B 课程资源接口

已落地 `/resources` 与 `/questions` 全部冻结接口。资源查询支持 `course_id`、`status`、`name`、`resource_type` 三维组合过滤；写入须分别具备 `resources:write`、`resources:review`、`resources:freeze` 权限。教师课程范围来自 `UserContext`，学生只能读取 `PUBLISHED`（已发布）或 `FROZEN`（已冻结）资源。

题库批量导入与独立审核接口冻结为：

```text
GET  /api/v1/questions/import-template.xlsx
POST /api/v1/questions/import
GET  /api/v1/questions/import-jobs/{job_id}
GET  /api/v1/questions/import-jobs/{job_id}/error-rows.xlsx
GET  /api/v1/questions/review-queue
POST /api/v1/questions/{question_id}/review
```

模板固定预置 49 个课时、每课时填空/单选/多选/判断各 1 行，共 196 行。导入请求必须携带基于文件内容摘要的 `Idempotency-Key`（幂等键）；同一键与同一文件返回同一任务，同一键对应不同内容固定返回冲突。服务端逐行校验课时、题型、题干、选项、答案和解析，并拒绝公式及以 `= + - @` 开头的危险单元格。任一行失败时整批不写入题目，任务保存全部逐行错误并可导出 XLSX（电子表格）错误明细；整批通过后 196 题统一进入 `PENDING_REVIEW`（待审核）队列。审核人必须具备 `resources:review` 权限、属于同一课程范围且不能是题目创建人；驳回必须填写原因，通过后题目发布。被驳回题目由原作者修改后重新进入 `PENDING_REVIEW`（待审核）队列，仍须由其他审核人复核后方可发布。

`POST /api/v1/resources/files` 接收受限类型的真实文件，按流式写入受控目录，同时计算 SHA256（文件校验值）、大小和媒体类型并登记公共 `file_object`（文件对象）；同内容重复上传复用已有文件对象。`GET /api/v1/resources/{resource_id}/download` 只允许下载受控目录中的已登记版本文件，学生只能下载已发布或已冻结资源。视频版本由 `ffprobe`（媒体探测工具）读取真实时长、宽度和高度，资源列表的 `latest_version.video` 返回这些解析结果；前端不得回退到原型示例时长。`GET /api/v1/resources/readiness` 返回 PPT（演示文稿）、理论/实验视频、实验文件包、题型覆盖和已审核题目数的动态就绪度。

资源版本只新增不覆盖，文件必须引用公共 `file_object.file_id`，且请求的 SHA256（文件校验值）必须与文件对象一致。资源类型与真实文件媒体类型必须一致。发布顺序为 `DRAFT（草稿） -> PENDING_REVIEW（待审核） -> PUBLISHED（已发布） -> FROZEN（已冻结）`；制作人与审核人必须不同。

完整性审计按 37 个理论课时的 PPT（演示文稿）/视频/题型/审核，以及 12 个实验课时的介绍/文件包/视频/题型实时计算 196 个检查点。PPT（演示文稿）、视频和实验文件包必须由同一已发布版本提供文件、专项质量证据与独立审核记录；理论视频只有真实解析时长位于 2100～2700 秒（35～45 分钟）才通过“约 40 分钟”门禁，实验视频必须具有大于零的真实解析时长；实验介绍必须同时具备目的、环境、原理和步骤摘要；已发布题目必须有非空答案、解析、课时映射和独立审核人。每个检查点返回可追溯的资源、版本、文件、审核或题目标识。`blocking > 0` 时 `POST /api/v1/resources/delivery/freeze` 固定返回 `RESOURCE.DELIVERY_BLOCKED`，清单可导出 JSON（结构化数据）和 XLSX（电子表格）。

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
