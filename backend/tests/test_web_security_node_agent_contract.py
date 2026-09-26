from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from node_agent.app import approved_command, approved_command_paths


@pytest.mark.parametrize("number", [1, 8, 9, 10])
def test_original_web_security_graders_are_fixed_and_evidence_scoped(number: int):
    ref = f"verify_web{number:02d}"
    command = approved_command(ref)
    paths = approved_command_paths(ref)
    assert command[:2] == ["python3", "-c"]
    assert paths
    assert all(path.startswith("work/") for path in paths)


def test_web_security_graders_do_not_accept_teacher_supplied_commands():
    with pytest.raises(HTTPException):
        approved_command("verify_web_custom_shell")
