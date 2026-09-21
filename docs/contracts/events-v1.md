# 领域事件契约 v1

所有事件使用以下信封：`event_id`、`event_type`、`aggregate_type`、`aggregate_id`、`actor_user_id`、`occurred_at`、`idempotency_key`、`payload`。

首批事件：

`attendance.completed`、`poll.completed`、`assignment.submitted`、`quiz.completed`、`lab.release.published`、`lab.instance.started`、`lab.checkpoint.passed`、`lab.checkpoint.failed`、`lab.submitted`、`lab.instance.failed`、`lab.instance.destroyed`、`grade.event.created`、`gradebook.posted`、`course.archived`。

业务事实和 `domain_event_outbox` 必须同一数据库事务写入。消费者必须按 `event_id` 或同一事件类型的 `idempotency_key` 幂等处理，禁止将消息队列当作权威事实库。

总控投递器按冻结路由消费事件箱：`lab.instance.*`、`lab.checkpoint.*`、`lab.submitted` 投影至 E；成绩事实事件和 `course.roster.frozen`、`resource.delivery.frozen` 送至 F；`lab.release.published` 送至 D。只有全部目标成功后才写 `published_at`，部分成功可依靠消费者幂等安全重试。

B 课程资源域追加事件：`resource.created`、`resource.version.created`、`resource.submit.review`、`resource.approve`、`resource.reject`、`resource.publish`、`resource.audit.completed`、`resource.delivery.frozen`、`question.created`、`question.updated`、`question.published`。事件载荷只携带冻结标识和必要摘要，不携带文件二进制或永久公开地址。

C 线新增事件：`lab.definition.created`、`lab.version.cloned`、`lab.version.updated`、`lab.version.validated`、`lab.version.published`、`lab.template.created`、`lab.knowledge.created`、`lab.knowledge.updated`、`lab.release.created`、`lab.release.preflighted`、`lab.release.preview.requested`。正式发布继续使用首批冻结事件 `lab.release.published`。

`lab.release.published` 必须携带 `lab_version_id`、`course_id`、`class_id`、`status` 和发布时的 `spec_snapshot`（规范快照）；D 使用该快照登记 `runtime_release_read_model`，不得在事件消费时读取 C 的业务表。

F 消费 `attendance.completed`、`assignment.submitted`、`quiz.completed`、`lab.checkpoint.passed`、`lab.checkpoint.failed`、`lab.submitted`、`poll.completed`，并输出 `grade.event.created`、`gradebook.posted`、`course.archived`。`lab.submitted` 的 `source_id` 固定为提交事实标识，`lab_release_id` 固定为实验发布标识。归档门禁还记录 `course.roster.frozen` 和 `resource.delivery.frozen` 的只读证据，不复制 A/B 业务事实；名单冻结证据必须同时匹配 `course_id` 与 `class_id`。

`course.roster.frozen` 还必须携带 `member_count`、`snapshot_hash` 和 `frozen_at`；A 冻结后拒绝任何名单增删和再次导入。
