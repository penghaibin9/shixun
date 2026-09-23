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

冻结规则：每一个成功的 JSON（数据文本）响应必须引用具名响应模型，不允许空对象或“任意对象”兜底；文件下载必须明确标为对应二进制媒体类型，SSE（服务器推送事件）必须明确标为事件流。契约测试会阻止这三类接口退化为未说明的 JSON 响应。

已落地的总控接口：`GET /api/v1/auth/context`，从身份提供方解析请求用户、角色、权限及课程/班级范围。`POST /api/v1/auth/users`、`GET /api/v1/auth/users`、`GET /api/v1/auth/users/{user_id}` 仅管理员可创建和查询不含密码/认证凭据的最小账号档案；创建必须提供外部主体标识或登录名，学生还必须提供学号。`POST /api/v1/auth/reconciliation/scan` 仅管理员可扫描历史名单差异，固定只新增核对事项而不改写 `class_membership`。生产身份由认证中间件注入；开发环境请求头仅在两个显式环境变量同时启用时用于契约测试，不能作为生产认证方案。

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

新增成员和 XLSX（电子表格）导入只接受学号与姓名，服务端按已有、启用的 `student_profile` 解析全局 `student_id`；客户端不得提交学生标识。未知/停用学号、姓名冲突和历史身份冲突会保留在导入任务逐行错误中，并写入可审计身份核对事项；同一学号加入不同班级时必须复用同一 `student_id`。

## A 作业、测验与服务端评分

`POST /api/v1/assignments` 与 `POST /api/v1/quizzes` 的每个题目选择只接受已发布题目的 `question_id`（题目标识）。客户端传入 `question_version`（题目版本）、`question_snapshot`（题目快照）、`max_score`（满分）或其他未知字段固定返回 422（请求内容不合法）；A 从 B 的独立审核、已发布题目冻结版本、题目快照、分值和判分依据。未发布、跨课程、课时不匹配、重复、未独立审核或不可自动判分的题目均不创建教学任务。

学生页面只能经以下受控只读接口读取本人已发布任务，不能从浏览器本地存储或页面常量拼接任务和题目：

```text
GET /api/v1/assignments/my
GET /api/v1/assignments/{assignment_id}/student-task
GET /api/v1/quizzes/my
GET /api/v1/quizzes/{quiz_id}/student-task
```

任务详情的 `questions` 只返回服务端签发的 `question_ref_id`（冻结题目引用）、题干、题型和可见选项；绝不返回标准答案、完整题目快照、版本摘要或分值。学生提交仍只允许以该引用为键的 `answers`（作答），服务端重新读取并校验完整冻结事实后判分。

`POST /api/v1/assignments/{assignment_id}/submit` 与 `POST /api/v1/quizzes/{quiz_id}/attempts/{attempt_id}/submit` 只接受 `answers`（作答）。`raw_score`（原始分）、`max_score`（满分）、`source_proof`（来源证明）和其他未知字段固定拒绝；服务端基于冻结题集和保存的作答重新计算分数，创建 A 自有 `teaching_score_proof`（教学评分证明事实）及配对的事务事件箱记录。作业或测验的历史提交如果没有服务端证明，重放固定返回 `TEACHING.LEGACY_SCORE_UNVERIFIED`（历史评分不可复核），不会将旧的客户端评分作为安全成绩返回。详细事件字段与可复核摘要规则见 `docs/contracts/teaching-score-proof-v1.md`。

## 总控事件投递接口

`POST /api/v1/integration/outbox/dispatch` 仅允许 `service_` 前缀的管理员服务身份并要求 `integration:dispatch` 权限。投递器从 `domain_event_outbox` 读取未发布事件：D 运行事件写入 E 课堂投影并送入 F 成绩事实，A/B 冻结事件送入 F 归档证据，C 的 `lab.release.published` 携带不可变实验规范快照写入 D 发布上下文。任一目标失败时事件保持未发布，可安全重试；各消费者按 `event_id` 幂等。

## D/E 课堂运行事实读取

教师页面 `GET /api/v1/classroom/lab-releases/{release_id}/summary` 与 `GET /api/v1/classroom/lab-releases/{release_id}/students` 固定以 D 的 `runtime/lab-releases/*` 冻结运行读模型作为状态、进度、得分和实例编号的唯一来源；E 仅用 A 的有效 `class_membership` 名单补齐未启动学生。响应固定标注 `runtime_fact_source: "D_RUNTIME_RELEASE_READ_MODEL"`；没有 D 运行记录的学生只能得到 `NOT_STARTED`，其 `current_step`、`total_steps`、`raw_score`、`max_score` 均为 `null`，不得补写默认步骤或 `0/100` 分数。

E 的本地运行事件投影只用于学习汇总和 SSE（服务端事件流）刷新通知，不能覆盖教师课堂读接口的 D 运行事实。D 返回的课程、班级、实验发布或学生名单与当前冻结范围不一致时，E 返回明确的 `502` 错误，不把异常数据聚合为课堂统计。高风险运行处置只有在 D 成功接受后才写审计事件；日志分发只有在 D 返回同一课程、班级和实验发布范围内的足量来源后才创建任务、审计和发件箱事件。

## D/E 日志分发下载授权

学生通过 E 的 `GET /api/v1/teaching-logs/my-assignments/{assignment_id}/download` 请求本人日志任务。E 校验分配事实、学生身份、课程、班级和实验发布后，向 D 的内部接口 `POST /api/v1/runtime/log-artifacts/distribution-bundle-url` 提交最长 60 秒的签名授权。授权精确绑定 `assignment_id`、`distribution_id`、日志类型、学生、课程、班级、实验发布、引用集合和随机数；D 重新验证签名、有效期、学生范围以及每个运行日志源事实后，才换取独立的短期存储能力。

该授权只使用 `runtime.distributed-artifact.download` 窄权限，不改变普通制品接口的实例所有权规则。跨学生、跨班级、跨实验发布、篡改引用和过期授权固定拒绝；同一授权重放返回相同能力并只追加一条 `runtime.artifact.distribution_download_authorized` 审计事件。E 与 D 共享的分发签名密钥和 D 与制品服务共享的存储签名密钥必须分离。

D 签发的存储能力固定使用 `issuer=lab-runtime`、`audience=artifact-storage`，绑定下载账号、授权类型、任务或下载包标识、完整引用集合、每项 `file_id + sha256 + size_bytes`、随机数及不超过 120 秒的签发/过期时间。`GET /api/v1/artifact-storage/bundles/{assignment_id}` 消费该能力并返回真实 ZIP（压缩包）；下载时重新查询 D 源事实和公共 `file_object`（文件对象），逐项流式计算大小与 SHA256（文件校验值），任一登记缺失、元数据变化、文件缺失、摘要错误或路径越界即拒绝整包。同一能力重复下载只追加一条下载审计事件。审计日志分发按运行事件事实生成规范化 JSON（结构化数据）条目，不伪造 `file_object`。

普通 `POST /api/v1/runtime/log-artifacts/{artifact_id}/download-url` 与 `POST /api/v1/runtime/log-artifacts/bundle-url` 使用同一存储端点和真实 ZIP（压缩包），能力绑定当前账号和精确引用集；下载端再次执行原有实例所有权校验，不能借普通下载跨学生或跨班级读取。

流量采集落盘/导入契约：Node Agent（节点代理）在运行组创建成功后接受 `POST /runtime-groups/{group_id}/capture/start`，控制面必须确认固定摘要抓包侧车已经进入 `CAPTURING（采集中）` 后才能把实验报告为 `RUNNING（运行中）`；启动失败必须回滚整个运行组。销毁、重建和恢复清理前，控制面调用 `POST /runtime-groups/{group_id}/capture/stop`，再通过受控制面身份保护的 `GET /runtime-groups/{group_id}/capture/artifact` 取回真实 PCAP（抓包文件）。停止响应、下载响应头和正文的运行组/采集标识、媒体类型、大小及 SHA256（文件校验值）必须全部相符；采集结束失败只记录明确失败，不能阻止随后销毁运行组。

控制面把验证后的文件原子写入 `YUEKE_RUNTIME_ARTIFACT_DIR` 指定的绝对根目录（默认 `backend/var/runtime_artifacts`），对象键固定为内容寻址的 `traffic/{sha256}.pcap`，拒绝相对根目录、符号链接、路径越界、非普通文件、空包或摘要不符。公共 `file_object` 登记固定为 `storage_provider=local`、`bucket=runtime-artifacts`，并与 `runtime_artifact.file_id/sha256/size_bytes` 逐项一致；同一实例同一摘要幂等复用，不得重复登记。Node Agent 必须配置白名单内的 `YUEKE_AGENT_CAPTURE_DIGEST` 固定镜像摘要和独立的 `YUEKE_AGENT_CAPTURE_DIR`，不得使用特权容器或挂载宿主 Docker Socket（容器运行接口）。下载端不接受任意外部 URL（网址）、其他存储桶、符号链接解析后的越界路径或未登记文件。

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

`POST /api/v1/grading/events/consume` 不接受仅带 `raw_score`（原始分）/`max_score`（满分）的分数事件。F 必须在同一 `domain_event_outbox`（事务事件箱）中核验完整信封和冻结聚合范围；作业、测验还必须通过独立的 `grading.score.proof.frozen`（评分证明已冻结）事件先写入 F 的 `grade_score_proof`（评分证明事实），最终成绩事件只携带 `score_proof_event_id` 引用。证明事件的 `actor_user_id` 固定为受信任服务 `service_teaching_score_prover`，并含 `issuer: teaching-core`、`origin: SERVER_GRADED`（服务端来源标记）、冻结题集、答题证据、判分证据及与目标分数和范围绑定的 SHA256（文件校验值）；最终成绩事件自己携带的同名摘要不构成证明。缺少、格式不合法、生产者不匹配或绑定不一致时接口返回 422（请求内容不合法）和 `GRADING.SOURCE_EVENT_UNVERIFIED`、`GRADING.SCORE_PROOF_REQUIRED`、`GRADING.SCORE_PROOF_PRODUCER_INVALID`、`GRADING.SCORE_PROOF_INVALID` 或 `GRADING.SOURCE_EVIDENCE_INVALID`，同时只追加 `GRADE_EVENT_REJECTED`（成绩事件已拒绝）审计事实，不会创建成绩事实。若引用的证明已在受控事件箱中但尚未由 F 消费，返回 `GRADING.SERVER_PROOF_PENDING`（服务端证明待到达）并追加 `GRADE_EVENT_DEFERRED`（成绩事件待证明），可安全重试。迁移前未证明的成绩保留为 `QUARANTINED_LEGACY`（历史隔离），不参与重算。

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
