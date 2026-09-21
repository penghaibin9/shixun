# D → E/F 运行事实契约 v1

D 只发布运行事实，不复制 A 的课程、班级或成员权威关系。消费者按 `event_id` 幂等消费；需要班级范围时由调用方携带每次解析的权限上下文，禁止跨库 SQL。

冻结业务事件：

- `lab.instance.started`
- `lab.instance.failed`
- `lab.instance.destroyed`
- `lab.checkpoint.passed`
- `lab.checkpoint.failed`
- `lab.submitted`

每个 payload 必含 `lab_release_id`、`course_id`、`class_id`、`student_id`、`runtime_instance_id`、`status`、`step`、`score`，并可带 `total_steps`、`max_score`、`started_at`、`last_activity_at`。同一实例生命周期或检查点尝试使用稳定幂等键；调度和运维审计事件只写 D 自有 `runtime_event`，不冒充冻结领域事件。

E 可通过以下只读接口构建课堂状态：

- `GET /api/v1/runtime/read-model/classes/{class_id}`
- `GET /api/v1/runtime/read-model/students/{student_id}`

班级接口只汇总 D 自有请求与实例状态；学生标识只是事件关联键，不在 D 保存姓名、学号、班级成员关系等 A 域事实。
