# 领域事件契约 v1

所有事件使用以下信封：`event_id`、`event_type`、`aggregate_type`、`aggregate_id`、`actor_user_id`、`occurred_at`、`idempotency_key`、`payload`。

首批事件：

`attendance.completed`、`poll.completed`、`assignment.submitted`、`quiz.completed`、`grading.score.proof.frozen`、`lab.release.published`、`lab.instance.started`、`lab.checkpoint.passed`、`lab.checkpoint.failed`、`lab.submitted`、`lab.instance.failed`、`lab.instance.destroyed`、`grade.event.created`、`gradebook.posted`、`course.archived`。

业务事实和 `domain_event_outbox` 必须同一数据库事务写入。消费者必须按 `event_id` 或同一事件类型的 `idempotency_key` 幂等处理，禁止将消息队列当作权威事实库。

总控投递器按冻结路由消费事件箱：`lab.instance.*`、`lab.checkpoint.*`、`lab.submitted` 投影至 E；成绩事实事件和 `course.roster.frozen`、`resource.delivery.frozen` 送至 F；`lab.release.published` 送至 D。只有全部目标成功后才写 `published_at`，部分成功可依靠消费者幂等安全重试。

B 课程资源域追加事件：`resource.created`、`resource.version.created`、`resource.submit.review`、`resource.approve`、`resource.reject`、`resource.publish`、`resource.audit.completed`、`resource.delivery.frozen`、`question.created`、`question.updated`、`question.published`、`question.rejected`、`question.import.completed`、`question.import.validation_failed`。事件载荷只携带冻结标识和必要摘要，不携带文件二进制或永久公开地址。题库导入完成/失败事件使用导入任务标识作为聚合标识；单题创建、发布和驳回事件使用题目标识作为聚合标识。上述 B 域事件由总控投递器幂等归档至公共 `audit_event`（审计事件）表，成功归档后才标记事件箱已发布。

C 线新增事件：`lab.definition.created`、`lab.version.cloned`、`lab.version.updated`、`lab.version.validated`、`lab.version.published`、`lab.template.created`、`lab.knowledge.created`、`lab.knowledge.updated`、`lab.release.created`、`lab.release.preflighted`、`lab.release.preview.requested`。正式发布继续使用首批冻结事件 `lab.release.published`。

`lab.release.published` 必须携带 `lab_version_id`、`course_id`、`class_id`、`status` 和发布时的 `spec_snapshot`（规范快照）；D 使用该快照登记 `runtime_release_read_model`，不得在事件消费时读取 C 的业务表。

## A 作业与测验服务端评分事实（冻结）

A 创建作业或测验只接受 B 题库中独立审核、已发布题目的 `question_id`（题目标识）。题目版本、快照、标准答案、选项和每题分值都在 A 服务端冻结；浏览器给出的快照、版本、分数或评分证明固定拒绝。提交只保存作答，A 从冻结题集和已保存作答计算原始分与满分，并在同一事务写入 A 自有的 `teaching_score_proof`（教学评分证明事实）、独立证明事件与最终成绩事件。

`grading.score.proof.frozen` 的 `actor_user_id`（操作者标识）固定为 `service_teaching_score_prover`，聚合类型为 `assignment_submission`（作业提交）或 `quiz_attempt`（测验作答），聚合标识等于 `source_fact_id`（来源事实标识）。其载荷固定携带 `score_event_id`、`score_event_type`、`score_aggregate_id`、`source_fact_id`、课程/班级/课时/学生、服务端 `raw_score`（原始分）/`max_score`（满分）和 `source_proof`（来源证明）。`source_proof` 使用 `grading-score-proof/v1`，包含题目数、冻结题集/答题/判分摘要以及绑定最终事件和分数范围的 `score_payload_sha256`（评分载荷校验值）。证明事件发生时间固定早于同事务的最终成绩事件一秒；最终 `assignment.submitted` 或 `quiz.completed` 在正常成绩范围字段之外只携带 `score_proof_event_id`（评分证明事件标识）作为证明引用，不重复携带证明。完整字段与摘要计算规则见 `teaching-score-proof-v1.md`。

F 消费 `attendance.completed`、`assignment.submitted`、`quiz.completed`、`lab.checkpoint.passed`、`lab.checkpoint.failed`、`lab.submitted`、`poll.completed`、`grading.score.proof.frozen`，并输出 `grade.event.created`、`gradebook.posted`、`course.archived`。`lab.submitted` 的 `source_id` 固定为提交事实标识，`lab_release_id` 固定为实验发布标识。归档门禁还记录 `course.roster.frozen` 和 `resource.delivery.frozen` 的只读证据，不复制 A/B 业务事实；名单冻结证据必须同时匹配 `course_id` 与 `class_id`。

## F 成绩来源证明（冻结）

F 在消费成绩或归档冻结事件前，必须按 `event_id` 查到同一不可变 `domain_event_outbox`（事务事件箱）记录，并逐字段比对 `event_type`、聚合类型/标识、操作者、发生时间、幂等键和规范化后的完整载荷。事件箱不存在、信封或载荷被替换、或聚合范围不符合下表时，均不是成绩事实。

| 事件 | 冻结聚合类型 | 可接受的证明路径 |
| --- | --- | --- |
| `attendance.completed` | `attendance_task` | 受控事件箱逐字段匹配 |
| `poll.completed` | `poll` | 受控事件箱逐字段匹配 |
| `lab.checkpoint.passed` / `lab.checkpoint.failed` | `runtime_instance` | 受控事件箱逐字段匹配，且 `runtime_instance_id` 等于聚合标识、携带 `lab_release_id`、`checkpoint_id` 与对应 `checkpoint_status` |
| `lab.submitted` | `runtime_instance` | 受控事件箱逐字段匹配，且 `runtime_instance_id` 等于聚合标识、携带 `lab_release_id` 和 `submission_status: SUBMITTED` |
| `grading.score.proof.frozen` | `assignment_submission` 或 `quiz_attempt` | 独立受控事件箱逐字段匹配，写入 F 的不可修改 `grade_score_proof`（评分证明事实） |
| `assignment.submitted` | `assignment` | 受控事件箱逐字段匹配，且引用已经持久化的评分证明事实 |
| `quiz.completed` | `quiz` | 受控事件箱逐字段匹配，且引用已经持久化的评分证明事实 |

`grading.score.proof.frozen` 必须在 A 的服务端完成冻结题集和判分后、与上游事务事件箱同事务写入；普通提交接口不得写入该事实。其 `actor_user_id` 固定为 `service_teaching_score_prover`，F 同时核对该受信任生产者和事件箱信封，不能只信载荷中的 `issuer`。聚合类型按目标成绩事件固定为 `assignment_submission` 或 `quiz_attempt`，聚合标识等于 `source_fact_id`。载荷固定包含目标 `score_event_id`、`score_event_type`、`score_aggregate_id`、`source_fact_id`、课程/班级/学生/课时、原始分/满分和 `source_proof`。`source_proof` 固定使用 `contract: grading-score-proof/v1`，并必须包含：`issuer: teaching-core`、`origin: SERVER_GRADED`（服务端来源标记）、目标成绩事件和提交事实标识、冻结题集类型（作业为 `ASSIGNMENT_FROZEN_QUESTION_SET`，测验为 `QUIZ_FROZEN_QUESTION_SET`）、正整数题目数、冻结题集/答题证据/判分证据的三个 SHA256（文件校验值），以及 `score_payload_sha256`。最后一个摘要必须重算并绑定目标事件、聚合、课程/班级/学生/课时、原始分/满分和前述证明字段；证明只保存摘要，不传递答案原文或凭据。

随后 `assignment.submitted` 或 `quiz.completed` 只携带 `score_proof_event_id` 引用已持久化的证明事件；F 重新核对引用事实与分数事件的事件标识、聚合、课程/班级/学生/课时、提交事实及分数。最终成绩事件中自带的 `source_proof` 不作为证明依据，不能以“载荷自洽”绕过服务端事实。总控投递器对未发布事件按证明事件优先排序，因此同一批证明与成绩事件可确定地先证明、后计分；若成绩事件引用的证明尚未入库，F 写入 `GRADE_EVENT_DEFERRED`（成绩事件待证明）审计事实并保持可重试。

缺少证明引用、格式错误或摘要不匹配的证明固定拒绝，F 不创建 `grade_event`，并追加不可修改的 `audit_event`，动作是 `GRADE_EVENT_REJECTED`，其中记录拒绝码和最小原因。迁移前没有证明列的旧 `grade_event` 标为 `QUARANTINED_LEGACY`（历史隔离），保留追溯但不参与成绩册重算；只有 `VERIFIED_OUTBOX` 或 `VERIFIED_SCORE_PROOF` 才能进入成绩册。

`course.roster.frozen` 还必须携带 `member_count`、`snapshot_hash` 和 `frozen_at`；A 冻结后拒绝任何名单增删和再次导入。

D 在成功验证 E 的日志分发授权并签发存储能力时，追加 `runtime.artifact.distribution_download_authorized`。事件聚合标识使用 `student_log_assignment`，载荷只记录分发、学生、课程、班级、实验发布、日志类型、引用标识和过期时间，不记录签名密钥、授权字符串、存储能力或日志原文；同一 `assignment_id + nonce` 必须幂等。

D 在真实 ZIP（压缩包）完成逐项完整性校验并开始响应前追加 `runtime.artifact.distribution_bundle_downloaded`；普通所有权下载分别追加 `runtime.artifact.direct_download_authorized` 与 `runtime.artifact.direct_bundle_downloaded`。下载事件只记录授权类型、账号/学生范围和引用标识，不记录能力、签名密钥或日志内容；同一能力的重复消费按包标识与随机数组合幂等。
