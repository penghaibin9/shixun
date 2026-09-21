# C → D 实验运行联调契约 v1

C 线只定义实验和发起请求，不接触 Docker Engine（容器运行引擎）。教师预演在静态预检通过后调用 D 线：

`POST /api/v1/runtime/preview-requests`

请求字段：`lab_release_id`、`lab_version_id`、`mode=TEACHER_PREVIEW`、`requested_by`、`idempotency_key`。

成功响应至少返回：`runtime_request_id`。C 线只保存该请求标识，不把“已受理”当作“预演通过”。D 线未配置、网络失败或返回非成功状态时，C 线统一返回 `LAB.RUNTIME_PROVIDER_UNAVAILABLE`（运行服务不可用），禁止生成伪造的预演成功结果。

D 线取到 `lab_version_id` 后应通过冻结接口读取该不可变版本，并校验镜像 `infra_image_id + digest`、节点资源限制、隔离网络、DAG 与 checkpoint（得分点）判定配置。实际容器、网络和受限 grader（判定器）均由 D 线负责。
