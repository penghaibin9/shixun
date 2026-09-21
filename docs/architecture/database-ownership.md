# 数据库所有权冻结（v1）

| 所有者 | 表前缀或表名 | 约束 |
|---|---|---|
| 总控 | `file_object`、`domain_event_outbox`；后续认证表使用 `auth_*` | 认证、公共文件及可靠事件投递 |
| A | `course*`、`class*`、`teaching_*`、`attendance_*`、`poll*`、`assignment*`、`quiz*` | 课程、章节、课时和归班事实仅此处创建；教师学生管理必须复用 `class_membership` |
| B | `resource*`、`lesson_resource`、`ppt_asset`、`video_asset`、`lab_file_pack`、`question*` | `lesson_resource` 仅保存资源扩展和 A 的课程/课时外键，不保存课时标题、编号、类型、章节；文件必须引用 `file_id` |
| C | `lab_definition`、`lab_version`、`lab_scene*`、`lab_dag_*`、`lab_checkpoint`、`lab_release`、`lab_template`、`lab_knowledge_point`、`lab_explain_diagram`、`lab_image_binding`、`lab_publish_config`、`lab_question_knowledge_map` | 定义而不启动实例 |
| D | `runtime_*`、`infra_*`、`checkpoint_result` | 仅 D 可操作容器运行时 |
| E | `classroom_*`、`teaching_log_distribution_*`、`student_log_assignment` | 仅保留必要课堂事实 |
| F | `grading_*`、`grade*`、`analytics_*`、`audit_event`、`course_archive*`、`student_course_score`、`student_risk_flag` | 消费上游事实，不复造上游记录 |

迁移仅可新增：各线新增自己的 Alembic（数据库迁移）版本；`integration（集成）` 在出现多头时创建合并版本。每次集成都必须在全新 MySQL 8.4 空库执行升级。

机器可校验的逐表唯一归属冻结在 `docs/contracts/database-ownership-v1.json`。契约测试要求 SQLAlchemy（数据库映射层）当前登记的每张表恰好出现一次；新增、遗漏或重复认领都会阻断集成。

跨域课程引用必须以 A 的 `course`、`course_chapter`、`course_lesson` 为权威，并优先使用 `(course_id, lesson_id)` 复合外键阻止跨课程课时串联。B 可以在读模型中组合 A 的课时标题、编号、类型与章节信息，但不得把这些字段作为第二套可独立修改的课程目录。
