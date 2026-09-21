# C｜实验定义线：Lab Designer

**Codex 窗口：** C  
**工作分支：** `feat/lab-designer`  
**前置：** P0 Contract 已冻结。  
**主 Gate：** G3。

## 共同执行纪律

- 唯一产品/交互基线：`跃科网络空间安全实训平台_采购文件完善版_FINAL.html`
- 采购验收依据：湖南工商大学《网络空间安全实训平台项目采购文件》（HUTB[2026]062号）
- 开工先扫描当前仓库、已有 migrations/API/模型/组件/测试；能复用的一律复用，禁止重新造第二套同名业务事实。
- 原型负责页面结构、字段、按钮、三角色和 11 步闭环；正式工程必须把 JS 写死数据替换为真实 API、真实 MySQL、真实文件、真实 Docker/日志/成绩事实。
- 前端不得重新设计一套 UI。尽量忠实最终 HTML；`yk-select / yk-check / yk-radio` 要落成可复用 Vue 组件，不出现浏览器默认控件外观。
- 权威事实库使用 MySQL 8.4 / InnoDB。Redis 如使用，只能做锁、Pub/Sub、Terminal session 等瞬时能力，不能成为课程、实例、成绩、审计事实源。
- 页面数据路径固定：`Vue -> API -> Service -> Repository -> MySQL`。
- 每个写接口必须有鉴权、数据范围、输入校验、幂等/防重复（适用时）、审计事件和明确错误码。
- 各施工线只改自己的 ownership；跨域通过冻结 Contract 调用，禁止“顺手重构”别人模块。
- 除总控 P0 外，不要只交分析报告；必须实际修改代码、迁移、测试并形成可运行提交。
- 测试至少覆盖 pytest、真实 MySQL 集成、前端 build、关键前端测试、对应 Playwright；涉及 Docker 的 Gate 必须在 Linux Docker 环境真实跑。

---

## 1. 负责范围

实验总览、模板、知识点+讲解图、拓扑、节点、网络、设备信息、镜像绑定、DAG、得分点、判定规则、版本、发布配置、教师预演请求。

**C 定义实验，不运行 Docker。**

## 2. 原型页面

- `page-labs`
- `page-lab-templates`
- `page-course-knowledge`
- `page-lab-builder` 六步

## 3. 采购条款

### 知识点维护+讲解图
- 知识点
- 关联题目
- 讲解图
- 讲解文本
- 在线讲解

### 场景搭建
- 网络拓扑
- 网络环境
- 设备信息
- 节点自定义

### DAG
- 实验步骤
- 得分点
- 判定规则

判定类型至少：

```text
FILE_HASH
COMMAND_EXIT
FILE_EXISTS
PORT_LISTEN
HTTP_RESPONSE
```

## 4. 数据表 ownership

```text
lab_template
lab_definition
lab_version

lab_scene
lab_scene_node
lab_scene_network
lab_image_binding

lab_dag_node
lab_dag_edge
lab_checkpoint

lab_knowledge_point
lab_question_knowledge_map
lab_explain_diagram

lab_release
lab_publish_config
```

`lab_release` 只引用 A 的 course/class/lesson。  
镜像绑定引用 D 的 `infra_image_id + digest`。

## 5. 实验版本

已发布版本不可直接改：

```text
v3 PUBLISHED
-> clone
-> v4 DRAFT
-> validate
-> READY
-> publish
```

运行实例永远引用具体 `lab_version_id`。

## 6. Lab Definition JSON

必须支持导入/导出和 schema 校验：

```json
{
  "lab_definition_id": "lab_rsa",
  "version": 1,
  "name": "RSA 非对称加密算法实验",
  "duration_minutes": 60,
  "total_score": 100,
  "nodes": [],
  "networks": [],
  "image_bindings": [],
  "steps": [],
  "edges": [],
  "checkpoints": [],
  "runtime_policy": {
    "max_attempts": 3,
    "timeout_minutes": 60
  }
}
```

用 Pydantic/JSON Schema 强校验。

## 7. 场景拓扑

节点至少：

```text
node_key
display_name
role
network_env: ISOLATED/SHARED/CUSTOM
device_model
image_id
image_digest
cpu_limit
memory_mb
ip_policy
ports[]
startup_command
mounts[]
```

网络：

```text
network_key
cidr_policy
internet_access
egress_allowlist
student_isolation
```

C 只保存定义，不执行 docker network。

## 8. 知识点讲解图

三栏按原型：

左：知识点列表  
中：图预览  
右：关联题目、讲解图、讲解文本

```text
lab_knowledge_point
lab_question_knowledge_map
lab_explain_diagram
```

题目引用 B `question_id`，图片引用 `file_id`。

## 9. DAG / Checkpoint

```text
checkpoint_id
dag_node_id
name
score
judge_type
judge_target
judge_config_json
failure_message
timeout_seconds
order_no
```

总分必须等于实验 total_score，否则禁止发布。

安全：

- 判定脚本只是定义数据。
- 真执行只能交 D 的受限 grader。
- FastAPI 控制平面禁止直接 subprocess 执行教师脚本。
- 判定配置要长度/类型/审核校验。

## 10. API

```text
GET  /api/v1/labs
POST /api/v1/labs
GET  /api/v1/labs/{id}

POST /api/v1/labs/{id}/versions
GET  /api/v1/lab-versions/{id}
PATCH /api/v1/lab-versions/{id}
POST /api/v1/lab-versions/{id}/validate
POST /api/v1/lab-versions/{id}/publish
GET  /api/v1/lab-versions/{id}/export.json

GET  /api/v1/lab-templates
POST /api/v1/lab-templates

GET  /api/v1/lab-knowledge
POST /api/v1/lab-knowledge
PATCH /api/v1/lab-knowledge/{id}

POST /api/v1/lab-releases
POST /api/v1/lab-releases/{id}/preflight
POST /api/v1/lab-releases/{id}/teacher-preview
POST /api/v1/lab-releases/{id}/publish
```

teacher-preview 只调 D。

## 11. 第一阶段 RSA

只把一个实验做到最深：

```text
student-rsa
target-rsa

启动环境        0
生成密钥       20
公钥加密       20
私钥解密       30
签名验签       20
提交报告       10
```

Checkpoint 能表达：

- private/public.pem 存在且格式正确
- cipher.bin
- plain.out 与 source.txt SHA256 相同
- Verified OK
- report 存在

先过 G3，再用同 schema 扩其他采购实验，不为每种实验造新结构。

## 12. 12 实验映射

与 B 对接：

```text
01/02 AES/DES
03/04 RSA
05 MD5/SHA
06/07 Base64/LSB
08 DB 权限
09 脱敏
10 备份恢复
11 日志审计
12 综合
```

## 13. 前端

- 模板
- 拖拽拓扑
- 节点属性
- 网络环境/设备信息
- 镜像选择
- DAG
- checkpoint 编辑
- 判定类型/对象/脚本/失败提示
- 发布范围
- 发布门禁
- 教师预演

拖拽结果必须真实保存数据库。

## 14. 权限

- 教师只能改授权课程实验
- PUBLISHED 不可 PATCH
- 发布班级必须在 UserContext.class_ids
- 讲解图下载受权
- 发布/冻结均审计

## 15. 测试

- schema
- version immutability
- DAG cycle
- edge refs
- node/network refs
- checkpoint 总分
- judge type
- image digest
- class scope
- knowledge-question mapping

Playwright G3：

`模板 -> RSA -> 拓扑 -> 镜像 -> DAG -> 5 得分点 -> 总分100 -> 预检 -> 版本 -> 导出 JSON`

D 未好时预演可显示 provider unavailable，**禁止伪造 PASS**。

## 16. 不可触碰区

禁止：

- Docker Engine
- node_agent
- 真实镜像仓库管理
- 自建 student/class
- gradebook
- Web Terminal
- 控制平面执行 judge script

## 17. G3

必须证明：

- RSA 来自 DB
- immutable version
- 拓扑/网络/设备完整
- image digest 固定
- DAG 无环
- 得分 100
- 五类 judge 支持
- class_id 真实引用
- JSON 可导入导出
- 发布后不可覆盖

## 18. 完成后给我

- commit
- migration
- RSA JSON/schema
- API
- G3 测试
- 与 D 的 preflight/runtime 联调清单
