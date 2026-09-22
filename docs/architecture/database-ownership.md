# 数据库所有权冻结（v1）

| 所有者 | 表前缀或表名 | 约束 |
|---|---|---|
| 总控 | `auth_user`、`auth_role`、`auth_permission`、`auth_user_role`、`auth_role_permission`、`teacher_profile`、`student_profile`、`identity_reconciliation_case`、`file_object`、`domain_event_outbox` | 权威账号/角色/档案、历史身份核对事项、公共文件及可靠事件投递 |
| A | `course*`、`class*`、`teaching_*`、`attendance_*`、`poll*`、`assignment*`、`quiz*` | 课程、章节、课时和归班事实仅此处创建；教师学生管理必须复用 `class_membership` |
| B | `resource*`、`lesson_resource`、`ppt_asset`、`video_asset`、`lab_file_pack`、`question*` | `lesson_resource` 仅保存资源扩展和 A 的课程/课时外键，不保存课时标题、编号、类型、章节；文件必须引用 `file_id` |
| C | `lab_definition`、`lab_version`、`lab_scene*`、`lab_dag_*`、`lab_checkpoint`、`lab_release`、`lab_template`、`lab_knowledge_point`、`lab_explain_diagram`、`lab_image_binding`、`lab_publish_config`、`lab_question_knowledge_map` | 定义而不启动实例 |
| D | `runtime_*`、`infra_*`、`checkpoint_result` | 仅 D 可操作容器运行时 |
| E | `classroom_*`、`teaching_log_distribution_*`、`student_log_assignment` | 仅保留必要课堂事实 |
| F | `grading_*`、`grade*`、`grade_score_proof`、`analytics_*`、`audit_event`、`course_archive*`、`student_course_score`、`student_risk_flag` | 消费上游事实，不复造上游记录；作业/测验证明只由受控事件消费后持久化 |

迁移仅可新增：各线新增自己的 Alembic（数据库迁移）版本；`integration（集成）` 在出现多头时创建合并版本。每次集成都必须在全新 MySQL 8.4 空库执行升级。

机器可校验的逐表唯一归属冻结在 `docs/contracts/database-ownership-v1.json`。契约测试要求 SQLAlchemy（数据库映射层）当前登记的每张表恰好出现一次；新增、遗漏或重复认领都会阻断集成。

跨域课程引用必须以 A 的 `course`、`course_chapter`、`course_lesson` 为权威，并优先使用 `(course_id, lesson_id)` 复合外键阻止跨课程课时串联。B 可以在读模型中组合 A 的课时标题、编号、类型与章节信息，但不得把这些字段作为第二套可独立修改的课程目录。

`student_profile.student_number` 是学生全局身份解析入口；A 仅将其权威 `student_id` 写入 `class_membership`，因此同学号跨班保持同一身份。为保护已有数据，本轮不为历史 `class_membership.student_id` 追加会导致旧数据无法迁移的外键，也不自动改写它；差异由 `identity_reconciliation_case` 留存，管理员扫描后人工核对。

F 的分数型上游事件必须先与同一不可变 `domain_event_outbox`（事务事件箱）逐字段核对。作业和测验还必须引用由独立 `grading.score.proof.frozen`（评分证明已冻结）事件写入的 `grade_score_proof`（评分证明事实），其生产者固定为 `service_teaching_score_prover`；提交载荷自带的分数或摘要不能直接成为成绩事实。迁移前的 `grade_event` 固定标记为 `QUARANTINED_LEGACY`（历史隔离），仅保留追溯，不参与成绩册重算。
