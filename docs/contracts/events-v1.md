# 领域事件契约 v1

所有事件使用以下信封：`event_id`、`event_type`、`aggregate_type`、`aggregate_id`、`actor_user_id`、`occurred_at`、`idempotency_key`、`payload`。

首批事件：

`attendance.completed`、`poll.completed`、`assignment.submitted`、`quiz.completed`、`lab.release.published`、`lab.instance.started`、`lab.checkpoint.passed`、`lab.checkpoint.failed`、`lab.submitted`、`lab.instance.failed`、`lab.instance.destroyed`、`grade.event.created`、`gradebook.posted`、`course.archived`。

业务事实和 `domain_event_outbox` 必须同一数据库事务写入。消费者必须按 `event_id` 或同一事件类型的 `idempotency_key` 幂等处理，禁止将消息队列当作权威事实库。

F 消费 `attendance.completed`、`assignment.submitted`、`quiz.completed`、`lab.checkpoint.passed`、`lab.checkpoint.failed`、`lab.submitted`、`poll.completed`，并输出 `grade.event.created`、`gradebook.posted`、`course.archived`。`lab.submitted` 的 `source_id` 固定为提交事实标识，`lab_release_id` 固定为实验发布标识。归档门禁还记录 `course.roster.frozen` 和 `resource.delivery.frozen` 的只读证据，不复制 A/B 业务事实；名单冻结证据必须同时匹配 `course_id` 与 `class_id`。
