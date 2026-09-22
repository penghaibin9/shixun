# 教学评分证明契约 v1

本契约只描述 A（教学核心）输出给 F（成绩、学情与审计）的作业、测验评分事实；不改变 F 的成绩册归属。

## 输入边界

教师创建作业或测验时，请求中只能选择已发布的 `question_id`。A 在同一事务从 B（课程资源）的已发布题目读取题干、标准答案、选项、审核信息和课时映射，生成 `teaching-frozen-question/v1` 快照及其 SHA256（文件校验值）版本。浏览器提交 `question_version`、`question_snapshot` 或 `max_score` 固定拒绝。

学生提交时只允许 `answers`。`raw_score`、`max_score`、`source_proof` 及其他未知字段固定拒绝；A 用冻结快照和已保存作答重算每题得分，当前客观题规则为每题 10 分、全对得分、其余 0 分。题目、作答和判分证据都以 A 的持久化事实保存，不能由外部请求写入。

提交前，A 会重新计算冻结快照的题目版本摘要；快照、答案、题干、选项、审核信息或分值与摘要不一致时固定拒绝，不会用被改写的冻结行评分。旧提交若没有对应的服务端评分证明，重复提交固定返回 `TEACHING.LEGACY_SCORE_UNVERIFIED`（历史评分不可复核），不会把旧的客户端评分当作安全结果返回。

## A 的持久化证明事实

`teaching_score_proof` 归 A 所有。一条记录唯一绑定：

- 提交或作答事实 `source_fact_id`；
- 原成绩事件 `score_event_id`；
- 独立证明事件 `score_proof_event_id`；
- 课程、班级、课时、学生、任务及服务端计算出的原始分、满分；
- 冻结题目、作答和判分证据的 SHA256；
- 三份原始证据 JSON（结构化数据）及与事件范围和分数绑定的 `score_payload_sha256`。

服务端在提交事务结束前可调用 `verify_teaching_score_proof` 复核上述三类证据摘要、两条事件、来源提交/作答事实及派发顺序；作业会从已保存的作答映射重建答题摘要，测验还会复核每条已保存答题及其分值。任何不一致返回 `TEACHING.SCORE_PROOF_TAMPERED`（服务端评分证明被篡改或不一致）。该校验器不对浏览器暴露写入口。

## 配对事件

每一次成功的作业或测验提交必须在**同一个数据库事务**新增两条 `domain_event_outbox`（事务事件箱）记录：

1. `grading.score.proof.frozen`
   - `aggregate_type`：作业固定 `assignment_submission`，测验固定 `quiz_attempt`。
   - `aggregate_id`：对应 `source_fact_id`。
   - `actor_user_id`：固定服务端身份 `service_teaching_score_prover`。
   - payload 必含 `score_event_id`、`score_event_type`、`score_aggregate_id`、`source_fact_id`、课程/班级/课时/学生、服务端 `raw_score`/`max_score` 及下方的 `source_proof`。
2. 原成绩事件：`assignment.submitted` 或 `quiz.completed`
   - 聚合分别为 `assignment` 或 `quiz`。
   - payload 只携带课程/班级/课时/学生、`source_id`、服务端 `raw_score`/`max_score` 和 `score_proof_event_id`。
   - 不重复携带 `source_proof`，F 必须先消费独立证明事件。

证明事件的 `occurred_at`（发生时间）固定早于原成绩事件一秒。这样即使 MySQL（关系型数据库）未保留微秒，投递器按 `occurred_at, event_id` 排序时也会先派发证明；两条记录仍与提交事实原子提交。证明事件未成功消费时，原成绩事件必须保持可重试而不能被 F 计入成绩册。

## `source_proof` 冻结字段

证明事件的 `source_proof` 固定为：

```text
contract = grading-score-proof/v1
issuer = teaching-core
origin = SERVER_GRADED
evidence_type = ASSIGNMENT_FROZEN_QUESTION_SET | QUIZ_FROZEN_QUESTION_SET
source_event_id = score_event_id
source_fact_id = 提交或作答事实标识
frozen_question_count
frozen_question_sha256
answer_evidence_sha256
scoring_evidence_sha256
score_payload_sha256
```

`score_payload_sha256` 使用稳定 JSON（结构化数据）编码，绑定原成绩事件标识、事件类型、聚合、课程/班级/课时/学生、来源事实、原始分、满分和上述全部证明字段。它必须与 F 的独立重算规则一致；证明载荷不传递正确答案、学生答案原文或认证凭据。

F 以 `score_proof_event_id` 作为跨域唯一引用，先把证明事件写入 F 自有的不可修改证明投影，再接收原成绩事件。A 的 `proof_id` 仅留在 A 的持久化事实中，不是跨域写入参数。
