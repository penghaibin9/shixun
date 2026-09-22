"""enforce runtime fact ownership and lookup integrity

Revision ID: 20260922_0016
Revises: 20260922_0015
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0016"
down_revision = "20260922_0015"
branch_labels = None
depends_on = None


def _fail_if_rows(bind, sql: str, message: str) -> None:
    row = bind.execute(sa.text(sql)).first()
    if row:
        raise RuntimeError(f"{message}: {tuple(row)}")


def upgrade() -> None:
    bind = op.get_bind()

    orphan_checks = [
        (
            "SELECT h.heartbeat_id, h.node_id FROM infra_node_heartbeat h "
            "LEFT JOIN infra_node n ON n.node_id = h.node_id "
            "WHERE n.node_id IS NULL LIMIT 1",
            "节点心跳引用了不存在的计算节点，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT v.validation_id, v.image_id FROM infra_image_validation v "
            "LEFT JOIN infra_image i ON i.image_id = v.image_id "
            "WHERE i.image_id IS NULL LIMIT 1",
            "镜像验证引用了不存在的镜像，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT q.queue_id, q.runtime_request_id FROM runtime_queue q "
            "LEFT JOIN runtime_request r ON r.runtime_request_id = q.runtime_request_id "
            "WHERE r.runtime_request_id IS NULL LIMIT 1",
            "运行队列引用了不存在的启动请求，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT g.runtime_group_id, g.runtime_request_id FROM runtime_instance_group g "
            "LEFT JOIN runtime_request r ON r.runtime_request_id = g.runtime_request_id "
            "WHERE r.runtime_request_id IS NULL LIMIT 1",
            "运行组引用了不存在的启动请求，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT g.runtime_group_id, g.node_id FROM runtime_instance_group g "
            "LEFT JOIN infra_node n ON n.node_id = g.node_id "
            "WHERE n.node_id IS NULL LIMIT 1",
            "运行组引用了不存在的计算节点，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT i.runtime_instance_id, i.runtime_group_id FROM runtime_instance i "
            "LEFT JOIN runtime_instance_group g ON g.runtime_group_id = i.runtime_group_id "
            "WHERE g.runtime_group_id IS NULL LIMIT 1",
            "运行实例引用了不存在的运行组，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT c.runtime_container_id, c.runtime_instance_id FROM runtime_container c "
            "LEFT JOIN runtime_instance i ON i.runtime_instance_id = c.runtime_instance_id "
            "WHERE i.runtime_instance_id IS NULL LIMIT 1",
            "运行容器引用了不存在的运行实例，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT n.runtime_network_id, n.runtime_group_id FROM runtime_network n "
            "LEFT JOIN runtime_instance_group g ON g.runtime_group_id = n.runtime_group_id "
            "WHERE g.runtime_group_id IS NULL LIMIT 1",
            "运行网络引用了不存在的运行组，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT e.runtime_event_id, e.runtime_instance_id FROM runtime_event e "
            "LEFT JOIN runtime_instance i ON i.runtime_instance_id = e.runtime_instance_id "
            "WHERE e.runtime_instance_id IS NOT NULL AND i.runtime_instance_id IS NULL LIMIT 1",
            "运行事件引用了不存在的运行实例，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT e.runtime_event_id, e.runtime_group_id FROM runtime_event e "
            "LEFT JOIN runtime_instance_group g ON g.runtime_group_id = e.runtime_group_id "
            "WHERE e.runtime_group_id IS NOT NULL AND g.runtime_group_id IS NULL LIMIT 1",
            "运行事件引用了不存在的运行组，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT u.usage_id, u.runtime_instance_id FROM runtime_resource_usage u "
            "LEFT JOIN runtime_instance i ON i.runtime_instance_id = u.runtime_instance_id "
            "WHERE i.runtime_instance_id IS NULL LIMIT 1",
            "资源用量引用了不存在的运行实例，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT t.terminal_session_id, t.runtime_instance_id FROM runtime_terminal_session t "
            "LEFT JOIN runtime_instance i ON i.runtime_instance_id = t.runtime_instance_id "
            "WHERE i.runtime_instance_id IS NULL LIMIT 1",
            "终端会话引用了不存在的运行实例，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT a.runtime_artifact_id, a.runtime_instance_id FROM runtime_artifact a "
            "LEFT JOIN runtime_instance i ON i.runtime_instance_id = a.runtime_instance_id "
            "WHERE i.runtime_instance_id IS NULL LIMIT 1",
            "运行产物引用了不存在的运行实例，拒绝补齐运行时事实约束",
        ),
        (
            "SELECT c.checkpoint_result_id, c.runtime_instance_id FROM checkpoint_result c "
            "LEFT JOIN runtime_instance i ON i.runtime_instance_id = c.runtime_instance_id "
            "WHERE i.runtime_instance_id IS NULL LIMIT 1",
            "检查点结果引用了不存在的运行实例，拒绝补齐运行时事实约束",
        ),
    ]
    for sql, message in orphan_checks:
        _fail_if_rows(bind, sql, message)

    duplicate_checks = [
        (
            "SELECT runtime_group_id, node_key, COUNT(*) FROM runtime_instance "
            "GROUP BY runtime_group_id, node_key HAVING COUNT(*) > 1 LIMIT 1",
            "同一运行组存在重复节点实例，拒绝补齐运行时唯一约束",
        ),
        (
            "SELECT runtime_instance_id, COUNT(*) FROM runtime_container "
            "GROUP BY runtime_instance_id HAVING COUNT(*) > 1 LIMIT 1",
            "同一运行实例存在多个容器事实，拒绝补齐运行时唯一约束",
        ),
        (
            "SELECT provider_network_id, COUNT(*) FROM runtime_network "
            "GROUP BY provider_network_id HAVING COUNT(*) > 1 LIMIT 1",
            "底层网络标识被多个运行网络复用，拒绝补齐运行时唯一约束",
        ),
    ]
    for sql, message in duplicate_checks:
        _fail_if_rows(bind, sql, message)

    op.create_foreign_key(
        "fk_infra_node_heartbeat_node", "infra_node_heartbeat", "infra_node", ["node_id"], ["node_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_infra_image_validation_image", "infra_image_validation", "infra_image", ["image_id"], ["image_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_runtime_queue_request", "runtime_queue", "runtime_request", ["runtime_request_id"], ["runtime_request_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_runtime_group_request", "runtime_instance_group", "runtime_request", ["runtime_request_id"], ["runtime_request_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_runtime_group_node", "runtime_instance_group", "infra_node", ["node_id"], ["node_id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_runtime_instance_group", "runtime_instance", "runtime_instance_group", ["runtime_group_id"], ["runtime_group_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_runtime_container_instance", "runtime_container", "runtime_instance", ["runtime_instance_id"], ["runtime_instance_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_runtime_network_group", "runtime_network", "runtime_instance_group", ["runtime_group_id"], ["runtime_group_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_runtime_event_instance", "runtime_event", "runtime_instance", ["runtime_instance_id"], ["runtime_instance_id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_runtime_event_group", "runtime_event", "runtime_instance_group", ["runtime_group_id"], ["runtime_group_id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_runtime_usage_instance", "runtime_resource_usage", "runtime_instance", ["runtime_instance_id"], ["runtime_instance_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_runtime_terminal_instance", "runtime_terminal_session", "runtime_instance", ["runtime_instance_id"], ["runtime_instance_id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_runtime_artifact_instance", "runtime_artifact", "runtime_instance", ["runtime_instance_id"], ["runtime_instance_id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_checkpoint_result_instance", "checkpoint_result", "runtime_instance", ["runtime_instance_id"], ["runtime_instance_id"], ondelete="RESTRICT"
    )

    op.create_unique_constraint(
        "uq_runtime_instance_group_node", "runtime_instance", ["runtime_group_id", "node_key"]
    )
    op.create_unique_constraint(
        "uq_runtime_container_instance", "runtime_container", ["runtime_instance_id"]
    )
    op.create_unique_constraint(
        "uq_runtime_provider_network", "runtime_network", ["provider_network_id"]
    )
    op.create_index(
        "ix_runtime_group_node_status", "runtime_instance_group", ["node_id", "status", "scheduled_at"]
    )
    op.create_index(
        "ix_runtime_event_group_time", "runtime_event", ["runtime_group_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_checkpoint_result_instance", "checkpoint_result", type_="foreignkey")
    op.drop_constraint("fk_runtime_artifact_instance", "runtime_artifact", type_="foreignkey")
    op.drop_constraint("fk_runtime_terminal_instance", "runtime_terminal_session", type_="foreignkey")
    op.drop_constraint("fk_runtime_usage_instance", "runtime_resource_usage", type_="foreignkey")
    op.drop_constraint("fk_runtime_event_group", "runtime_event", type_="foreignkey")
    op.drop_constraint("fk_runtime_event_instance", "runtime_event", type_="foreignkey")
    op.drop_constraint("fk_runtime_network_group", "runtime_network", type_="foreignkey")
    op.drop_constraint("fk_runtime_container_instance", "runtime_container", type_="foreignkey")
    op.drop_constraint("fk_runtime_instance_group", "runtime_instance", type_="foreignkey")
    op.drop_constraint("fk_runtime_group_node", "runtime_instance_group", type_="foreignkey")
    op.drop_constraint("fk_runtime_group_request", "runtime_instance_group", type_="foreignkey")
    op.drop_constraint("fk_runtime_queue_request", "runtime_queue", type_="foreignkey")
    op.drop_constraint("fk_infra_image_validation_image", "infra_image_validation", type_="foreignkey")
    op.drop_constraint("fk_infra_node_heartbeat_node", "infra_node_heartbeat", type_="foreignkey")

    op.drop_index("ix_runtime_event_group_time", table_name="runtime_event")
    op.drop_index("ix_runtime_group_node_status", table_name="runtime_instance_group")
    op.drop_constraint("uq_runtime_provider_network", "runtime_network", type_="unique")
    op.drop_constraint("uq_runtime_container_instance", "runtime_container", type_="unique")
    op.drop_constraint("uq_runtime_instance_group_node", "runtime_instance", type_="unique")
