from app.contentpacks.adapters.atomic_red_team import parse_atomic_technique
from app.contentpacks.adapters.pwncollege import parse_dojo_manifest


def test_atomic_preview_imports_metadata_but_not_execution_commands():
    preview = parse_atomic_technique(b"""
attack_technique: T1003
display_name: Credential Dumping
atomic_tests:
  - name: Demo metadata
    auto_generated_guid: 00000000-0000-0000-0000-000000000001
    supported_platforms: [linux]
    executor:
      name: sh
      command: echo should-not-be-imported
""")
    assert preview.attack_technique == "T1003"
    assert preview.test_count == 1
    assert preview.execution_imported is False
    assert not hasattr(preview.tests[0], "command")


def test_pwncollege_preview_imports_module_structure_only():
    preview = parse_dojo_manifest(b"""
id: intro-demo
name: Intro Demo
modules:
  - id: web
    name: Web Security
  - id: crypto
""")
    assert preview.dojo_id == "intro-demo"
    assert preview.module_count == 2
    assert preview.content_imported is False
    assert [item.id for item in preview.modules] == ["web", "crypto"]
