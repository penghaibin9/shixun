# D ↔ E 实验课堂联调契约 v1

本契约服从 P0 的 `api-v1.md`、`events-v1.md` 与状态机。D 不保存姓名、学号或班级成员关系；E 使用 `student_id` 向 A 聚合展示信息。

## 发布上下文

C 发布实验后，以受信服务身份调用 `POST /api/v1/runtime/release-contexts`，提交 `lab_release_id`、`lab_version_id`、`course_id`、`class_id` 与发布状态。D 经 C 冻结版本接口校验后保存 `runtime_release_read_model`。未收到上下文时，D 对仅含学生标识的启动请求返回 `RUNTIME.RELEASE_CONTEXT_REQUIRED`，不猜测版本或跨库查询。

## E 兼容门面

- `GET /api/v1/runtime/lab-releases/{release_id}`
- `GET /api/v1/runtime/lab-releases/{release_id}/summary`
- `GET /api/v1/runtime/lab-releases/{release_id}/students`
- `GET /api/v1/runtime/lab-releases/{release_id}/students/{student_id}`
- `POST /api/v1/runtime/lab-releases/{release_id}/start`
- `POST /api/v1/runtime/lab-releases/{release_id}/submit`
- `POST /api/v1/runtime/lab-releases/{release_id}/extend-all`
- `POST /api/v1/runtime/lab-releases/{release_id}/remind-idle`
- `GET /api/v1/runtime/instances/{runtime_instance_id}`
- `POST /api/v1/runtime/instances/{runtime_instance_id}/{destroy|rebuild|extend|rejudge|remind|unlock}`
- `POST /api/v1/runtime/instances/{runtime_instance_id}/terminal-token`
- `GET /api/v1/runtime/logs/audit`
- `GET /api/v1/runtime/logs/traffic`
- `GET /api/v1/runtime/log-artifacts/{artifact_id}`
- `POST /api/v1/runtime/log-artifacts/{artifact_id}/download-url`
- `POST /api/v1/runtime/log-artifacts/bundle-url`

E 的受信服务转发可将 `classroom.*` 权限按最小动作映射为 D 的 `runtime.*` 权限；普通浏览器请求不获得双域权限。

业务排队返回 `202`，依赖或节点代理不可用才返回 `503`。请求状态固定为 `QUEUED/SCHEDULING/STARTING/RUNNING/FAILED/CANCELED`，实例状态固定为 `CREATED/STARTING/RUNNING/STOPPING/DESTROYED/FAILED`；接口额外返回中文 `display_status`。

## 终端

令牌响应同时提供 `websocket_path`、`websocket_url`、`expires_at`、`expires_in`、`token_transport=FIRST_FRAME`。浏览器建立 WebSocket 后必须把 `{ "token": "..." }` 作为第一帧发送；禁止把 token 放入查询参数或持久化存储。D 不提供查询参数兼容降级。

## 当前外部前置

- E 的 `TerminalPanel.vue` 仍把 token 拼到查询参数，必须改成首帧发送，否则 D 按安全策略拒绝。
- E 的运行事件输入枚举仍是 `runtime.started/checkpoint.passed/...`，必须改为 P0 的 `lab.instance.started/lab.checkpoint.passed/...`。
- 流量采集器与制品存储下载基地址未部署时，D 明确返回 `501/503`；不生成伪造下载地址。
