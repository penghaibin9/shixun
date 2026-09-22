import os

import pytest
from sqlalchemy import create_engine, inspect

from app.common.models import Base
from app.runtime import models  # noqa: F401


EXPECTED_FOREIGN_KEYS = {
    "infra_node_heartbeat": {"fk_infra_node_heartbeat_node": "CASCADE"},
    "infra_image_validation": {"fk_infra_image_validation_image": "CASCADE"},
    "runtime_queue": {"fk_runtime_queue_request": "CASCADE"},
    "runtime_instance_group": {"fk_runtime_group_request": "CASCADE", "fk_runtime_group_node": "RESTRICT"},
    "runtime_instance": {"fk_runtime_instance_group": "CASCADE"},
    "runtime_container": {"fk_runtime_container_instance": "CASCADE"},
    "runtime_network": {"fk_runtime_network_group": "CASCADE"},
    "runtime_event": {"fk_runtime_event_instance": "SET NULL", "fk_runtime_event_group": "SET NULL"},
    "runtime_cleanup_task": {"fk_runtime_cleanup_node": "RESTRICT"},
    "runtime_resource_usage": {"fk_runtime_usage_instance": "CASCADE"},
    "runtime_terminal_session": {"fk_runtime_terminal_instance": "CASCADE"},
    "runtime_artifact": {"fk_runtime_artifact_instance": "RESTRICT"},
    "checkpoint_result": {"fk_checkpoint_result_instance": "RESTRICT"},
}

EXPECTED_UNIQUES = {
    "runtime_admin_action": {"uq_runtime_admin_action_actor_key"},
    "runtime_cleanup_task": {"uq_runtime_cleanup_target"},
    "runtime_queue": {"uq_runtime_queue_request"},
    "runtime_instance": {"uq_runtime_instance_group_node"},
    "runtime_container": {"uq_runtime_provider_container", "uq_runtime_container_instance"},
    "runtime_network": {"uq_runtime_network_key", "uq_runtime_provider_network"},
}

EXPECTED_RECOVERY_COLUMNS = {
    "runtime_request": {"provision_owner", "provision_lease_expires_at"},
    "runtime_queue": {"processing_owner", "lease_expires_at"},
    "runtime_instance_group": {
        "provider_generation",
        "cleanup_attempts",
        "cleanup_not_before",
        "cleanup_intent",
        "cleanup_owner",
        "cleanup_lease_expires_at",
        "cleanup_error_code",
        "cleanup_error_message",
    },
    "runtime_admin_action": {
        "owner_token",
        "generation",
        "lease_expires_at",
        "error_details_json",
    },
    "runtime_cleanup_task": {
        "runtime_group_id",
        "provider_group_id",
        "provider_generation",
        "intent",
        "status",
        "attempts",
        "not_before",
        "processing_owner",
        "lease_expires_at",
        "error_code",
        "error_message",
    },
}


def _metadata_constraint_names(table_name: str, constraint_kind: str) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {
        constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == constraint_kind and constraint.name
    }


def test_runtime_models_declare_fact_ownership_and_identity_constraints():
    for table_name, expected in EXPECTED_FOREIGN_KEYS.items():
        actual = {
            constraint.name: constraint.ondelete
            for constraint in Base.metadata.tables[table_name].foreign_key_constraints
        }
        assert expected.items() <= actual.items()
    for table_name, expected in EXPECTED_UNIQUES.items():
        assert expected <= _metadata_constraint_names(table_name, "UniqueConstraint")
    for table_name, expected in EXPECTED_RECOVERY_COLUMNS.items():
        assert expected <= set(Base.metadata.tables[table_name].columns.keys())

    assert "ix_runtime_group_node_status" in {
        index.name for index in Base.metadata.tables["runtime_instance_group"].indexes
    }
    assert "ix_runtime_event_group_time" in {
        index.name for index in Base.metadata.tables["runtime_event"].indexes
    }


@pytest.mark.skipif(not os.getenv("YUEKE_DATABASE_URL"), reason="需要真实 MySQL 8.4 的 YUEKE_DATABASE_URL")
def test_mysql_runtime_fact_constraints_match_models():
    engine = create_engine(os.environ["YUEKE_DATABASE_URL"], pool_pre_ping=True)
    try:
        database = inspect(engine)
        for table_name, expected in EXPECTED_FOREIGN_KEYS.items():
            actual = {
                item["name"]: item.get("options", {}).get("ondelete", "RESTRICT").upper()
                for item in database.get_foreign_keys(table_name)
            }
            assert expected.items() <= actual.items()
        for table_name, expected in EXPECTED_UNIQUES.items():
            actual = {item["name"] for item in database.get_unique_constraints(table_name)}
            assert expected <= actual
        for table_name, expected in EXPECTED_RECOVERY_COLUMNS.items():
            actual = {item["name"] for item in database.get_columns(table_name)}
            assert expected <= actual
        assert "ix_runtime_group_node_status" in {
            item["name"] for item in database.get_indexes("runtime_instance_group")
        }
        assert "ix_runtime_event_group_time" in {
            item["name"] for item in database.get_indexes("runtime_event")
        }
    finally:
        engine.dispose()
