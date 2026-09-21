# 数据库所有权冻结（v1）

| 所有者 | 表前缀或表名 | 约束 |
|---|---|---|
| 总控 | `auth_*`、`file_object`、`domain_event_outbox` | 认证、公共文件及可靠事件投递 |
| A | `course_*`、`class_*`、`teaching_*` | 课程和归班事实仅此处创建；教师学生管理必须复用 `class_membership` |
| B | `resource_*`、`question_*` | 文件必须引用 `file_id` |
| C | `lab_definition`、`lab_version`、`lab_scene_*`、`lab_dag_*`、`lab_checkpoint`、`lab_release*` | 定义而不启动实例 |
| D | `runtime_*`、`infra_*`、`checkpoint_result` | 仅 D 可操作容器运行时 |
| E | `classroom_*`、`teaching_log_distribution_*` | 仅保留必要课堂事实 |
| F | `grading_*`、`analytics_*`、`audit_*`、`course_archive*` | 消费上游事实，不复造上游记录 |

迁移仅可新增：各线新增自己的 Alembic（数据库迁移）版本；`integration（集成）` 在出现多头时创建合并版本。每次集成都必须在全新 MySQL 8.4 空库执行升级。
