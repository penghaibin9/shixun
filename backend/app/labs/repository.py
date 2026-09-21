from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import models
from .schemas import LabDefinitionSpec


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:36-len(prefix)-1]}"


class LabRepository:
    def __init__(self, session: Session):
        self.session = session

    def definitions(self, course_ids: frozenset[str]) -> list[models.LabDefinition]:
        if not course_ids:
            return []
        return list(self.session.scalars(select(models.LabDefinition).where(models.LabDefinition.course_id.in_(course_ids)).order_by(models.LabDefinition.updated_at.desc())))

    def definition(self, definition_id: str) -> models.LabDefinition | None:
        return self.session.get(models.LabDefinition, definition_id)

    def latest_version(self, definition_id: str) -> models.LabVersion | None:
        return self.session.scalar(select(models.LabVersion).where(models.LabVersion.lab_definition_id == definition_id).order_by(models.LabVersion.version.desc()).limit(1))

    def version(self, version_id: str, *, lock: bool = False) -> models.LabVersion | None:
        statement = select(models.LabVersion).where(models.LabVersion.lab_version_id == version_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def add_definition(self, definition: models.LabDefinition, version: models.LabVersion, spec: LabDefinitionSpec) -> None:
        self.session.add_all([definition, version])
        self.session.flush()
        self.replace_version_detail(version.lab_version_id, spec)

    def replace_version_detail(self, version_id: str, spec: LabDefinitionSpec) -> None:
        scene_ids = list(self.session.scalars(select(models.LabScene.scene_id).where(models.LabScene.lab_version_id == version_id)))
        if scene_ids:
            self.session.execute(delete(models.LabScene).where(models.LabScene.scene_id.in_(scene_ids)))
        for model in (models.LabImageBinding, models.LabCheckpoint, models.LabDagEdge, models.LabDagNode):
            self.session.execute(delete(model).where(model.lab_version_id == version_id))
        scene_id = new_id("scn")
        self.session.add(models.LabScene(scene_id=scene_id, lab_version_id=version_id, name=spec.name))
        for network in spec.networks:
            self.session.add(models.LabSceneNetwork(
                network_id=new_id("net"), scene_id=scene_id, network_key=network.network_key,
                cidr_policy=network.cidr_policy, internet_access=network.internet_access,
                egress_allowlist_json=network.egress_allowlist, student_isolation=network.student_isolation,
            ))
        for node in spec.nodes:
            self.session.add(models.LabSceneNode(
                scene_node_id=new_id("node"), scene_id=scene_id, node_key=node.node_key,
                display_name=node.display_name, role=node.role, network_env=node.network_env.value,
                network_keys_json=node.network_keys, device_model=node.device_model,
                cpu_limit=node.cpu_limit, memory_mb=node.memory_mb, ip_policy=node.ip_policy,
                ports_json=node.ports, startup_command=node.startup_command, mounts_json=node.mounts,
                position_x=node.position_x, position_y=node.position_y,
            ))
        for binding in spec.image_bindings:
            self.session.add(models.LabImageBinding(
                image_binding_id=new_id("imgb"), lab_version_id=version_id, node_key=binding.node_key,
                infra_image_id=binding.infra_image_id, image_digest=binding.digest,
            ))
        for step in spec.steps:
            self.session.add(models.LabDagNode(
                dag_node_id=new_id("dagn"), lab_version_id=version_id, node_key=step.node_key,
                name=step.name, description=step.description, order_no=step.order_no,
            ))
        for edge in spec.edges:
            self.session.add(models.LabDagEdge(
                dag_edge_id=new_id("dage"), lab_version_id=version_id,
                from_node_key=edge.from_node_key, to_node_key=edge.to_node_key,
            ))
        for checkpoint in spec.checkpoints:
            self.session.add(models.LabCheckpoint(
                checkpoint_id=checkpoint.checkpoint_id, checkpoint_key=checkpoint.checkpoint_id,
                lab_version_id=version_id, dag_node_key=checkpoint.dag_node_id,
                name=checkpoint.name, score=checkpoint.score, judge_type=checkpoint.judge_type.value,
                judge_target=checkpoint.judge_target, judge_config_json=checkpoint.judge_config_json,
                failure_message=checkpoint.failure_message, timeout_seconds=checkpoint.timeout_seconds,
                order_no=checkpoint.order_no,
            ))

    def next_version_number(self, definition_id: str) -> int:
        current = self.session.scalar(select(func.max(models.LabVersion.version)).where(models.LabVersion.lab_definition_id == definition_id))
        return int(current or 0) + 1

    def templates(self) -> list[models.LabTemplate]:
        return list(self.session.scalars(select(models.LabTemplate).order_by(models.LabTemplate.created_at)))

    def knowledge(self, course_ids: frozenset[str]) -> list[models.LabKnowledgePoint]:
        if not course_ids:
            return []
        return list(self.session.scalars(select(models.LabKnowledgePoint).where(models.LabKnowledgePoint.course_id.in_(course_ids)).order_by(models.LabKnowledgePoint.updated_at.desc())))

    def question_ids(self, knowledge_id: str) -> list[str]:
        return list(self.session.scalars(select(models.LabQuestionKnowledgeMap.question_id).where(models.LabQuestionKnowledgeMap.knowledge_point_id == knowledge_id)))

    def diagrams(self, knowledge_id: str) -> list[models.LabExplainDiagram]:
        return list(self.session.scalars(select(models.LabExplainDiagram).where(models.LabExplainDiagram.knowledge_point_id == knowledge_id).order_by(models.LabExplainDiagram.order_no)))

    def replace_knowledge_children(self, knowledge_id: str, question_ids: list[str], diagrams: list) -> None:
        self.session.execute(delete(models.LabQuestionKnowledgeMap).where(models.LabQuestionKnowledgeMap.knowledge_point_id == knowledge_id))
        self.session.execute(delete(models.LabExplainDiagram).where(models.LabExplainDiagram.knowledge_point_id == knowledge_id))
        for question_id in dict.fromkeys(question_ids):
            self.session.add(models.LabQuestionKnowledgeMap(map_id=new_id("kqm"), knowledge_point_id=knowledge_id, question_id=question_id))
        for diagram in diagrams:
            self.session.add(models.LabExplainDiagram(diagram_id=new_id("diag"), knowledge_point_id=knowledge_id, file_id=diagram.file_id, title=diagram.title, order_no=diagram.order_no))

    def release(self, release_id: str, *, lock: bool = False) -> models.LabRelease | None:
        statement = select(models.LabRelease).where(models.LabRelease.lab_release_id == release_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def publish_config(self, release_id: str) -> models.LabPublishConfig | None:
        return self.session.scalar(select(models.LabPublishConfig).where(models.LabPublishConfig.lab_release_id == release_id))

