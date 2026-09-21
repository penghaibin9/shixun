# Learning Summary（学习摘要）只读模型

接口：`GET /api/v1/analytics/courses/{course_id}/learning-summary?class_id={class_id}&student_id={student_id}`

`class_id` 为必填作用域；服务必须同时校验 `course_id`、`class_id` 是否位于 `UserContext`（用户上下文）授权范围，禁止缺少班级时回退为“课程最新成绩册”。A 线 façade（聚合门面）负责将 `class_membership`（班级成员关系）映射为 `class_id`、`student_id` 与 `course_id`。

用途：为教师/学生管理 CR（变更请求）提供成绩、教学风险和课程学情摘要。该接口不创建或修改 A 线的 `class_membership`（班级成员关系），也不替代学生管理页面。

状态：

- `PENDING（待处理）`：尚无上游事实或尚未重算。
- `PARTIAL（部分数据）`：已有部分成绩/学情，但缺少完整来源或尚未入账。
- `READY（就绪）`：成绩已入账、课程学情已计算。

学生请求强制使用 `UserContext.student_id`，响应只包含本人总评、本人风险、班级汇总指标和本人名次，不返回其他学生标识。教师请求仍受 `course_ids`、`class_ids` 数据范围约束。
