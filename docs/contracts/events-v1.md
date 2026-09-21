# 领域事件契约 v1

所有事件使用以下信封：`event_id`、`event_type`、`aggregate_type`、`aggregate_id`、`actor_user_id`、`occurred_at`、`idempotency_key`、`payload`。

首批事件：

`attendance.completed`、`poll.completed`、`assignment.submitted`、`quiz.completed`、`lab.release.published`、`lab.instance.started`、`lab.checkpoint.passed`、`lab.checkpoint.failed`、`lab.submitted`、`lab.instance.failed`、`lab.instance.destroyed`、`grade.event.created`、`gradebook.posted`、`course.archived`。

业务事实和 `domain_event_outbox` 必须同一数据库事务写入。消费者必须按 `event_id` 或同一事件类型的 `idempotency_key` 幂等处理，禁止将消息队列当作权威事实库。

C 线新增事件：`lab.definition.created`、`lab.version.cloned`、`lab.version.updated`、`lab.version.validated`、`lab.version.published`、`lab.template.created`、`lab.knowledge.created`、`lab.knowledge.updated`、`lab.release.created`、`lab.release.preflighted`、`lab.release.preview.requested`。正式发布继续使用首批冻结事件 `lab.release.published`。
