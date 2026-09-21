# B｜课程资源线：Course Resources

**Codex 窗口：** B  
**工作分支：** `feat/course-resources`  
**前置：** P0 Contract 已冻结。  
**采购主目标：** 37 理论课时（满足不少于 36）+ 12 实验课时。

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

资源总览、课程蓝图、**37 个理论课时**、12 个实验课时、PPT/讲义、理论/实验视频、题库、实验文件包、资源版本、审核、完整性审计、采购条款映射、Delivery Manifest。

不负责课程/班级事实、Docker、实验课堂、正式成绩。

## 2. 原型页面

- `page-resources`
- `page-course-blueprint`
- `page-course-theory`
- `page-course-lab-lessons`
- `page-course-ppt`
- `page-course-video`
- `page-course-questions`
- `page-course-procurement`
- `page-course-resource-audit`
- `page-course-delivery`

## 3. 采购要求

### 课程资源管理
按：

```text
发布状态
资源名称
资源类型
```

筛选，并支持新增资源。

### 理论资源
采购不少于 36；最终产品基线固定 **37**。

每课时：

- PPT
- 约 40 分钟讲解视频
- 3～4 道题
- 覆盖填空/单选/多选/判断

为降低验收风险，默认 4 题、四种题型各 1。

### 实验资源
12 课时，每课时：

- 目的
- 环境
- 原理
- 步骤文档
- 附件/工具
- 讲解视频
- 3～4 道练习

## 4. 37 理论课时硬校验

不得回退旧 36。

必须完整：

```text
3.6 数据存储加密（内容加密/磁盘加密）
    与传输加密（信源加密/通道加密）

4.2 经典脱敏算法
    （替换/仿真/加密/遮掩/混淆/偏移/取整）

7.3 行业数据安全治理实践
    （医疗/政务/工业领域案例）

7.4 典型数据安全产品选型指南
    （加密类/脱敏类/审计类/管控类/备份类）
```

章节：

```text
5 + 3 + 6 + 7 + 7 + 5 + 4 = 37
```

## 5. 12 实验课时映射

```text
实验01/02 -> AES/DES
实验03/04 -> RSA
实验05    -> MD5/SHA
实验06/07 -> Base64/隐写
实验08    -> 数据库权限分级
实验09    -> 数据脱敏
实验10    -> 备份与灾难恢复
实验11    -> 日志审计与溯源
实验12    -> 综合实践
```

B 管课时资源；真正 lab_definition 由 C 管，通过 `linked_lab_definition_id` 引用。

## 6. 数据表 ownership

```text
resource
resource_version
lesson_resource
resource_review
resource_quality_check
resource_delivery_manifest

ppt_asset
video_asset
lab_file_pack

question_bank
question
question_option
question_explanation
question_lesson_map
```

文件引用总控 `file_object.file_id`。

资源版本不可覆盖历史：

```text
resource_id
version_no
file_id
status
sha256
created_by
created_at
reviewed_by
reviewed_at
published_at
```

## 7. API

```text
GET  /api/v1/resources
POST /api/v1/resources
GET  /api/v1/resources/{id}
POST /api/v1/resources/{id}/versions
POST /api/v1/resources/{id}/submit-review
POST /api/v1/resources/{id}/approve
POST /api/v1/resources/{id}/reject
POST /api/v1/resources/{id}/publish

GET /api/v1/resources/course-blueprint/{course_id}
GET /api/v1/resources/theory-lessons
GET /api/v1/resources/lab-lessons

GET  /api/v1/questions
POST /api/v1/questions
PATCH /api/v1/questions/{id}
POST /api/v1/questions/{id}/review
GET  /api/v1/questions/coverage

POST /api/v1/resources/audit/run
GET  /api/v1/resources/audit/latest
POST /api/v1/resources/delivery/freeze
GET  /api/v1/resources/delivery/manifest.json
GET  /api/v1/resources/delivery/manifest.xlsx
```

course/lesson 本体来自 A，B 不创建第二套。

## 8. 文件与视频

上传：

```text
申请上传
-> file_object
-> 对象存储
-> SHA256/大小/MIME
-> resource_version
-> 审核
-> 发布
```

视频：

- 用 ffprobe 或已有媒体解析读取真实 duration。
- 理论视频目标约 40 分钟，UI 显示真实时长。
- 实验视频有真实 duration 和审核状态。
- 禁止把原型 `40:16` 当真实验收数据。

PPT 质量 Gate：

```text
知识点完整
版式溢出
动画遮挡复核
版权标注
```

“动画不覆盖页面”需要内容抽检，所以必须保留检查人、时间、结果，不能伪造自动证明。

## 9. 题库 Gate

每理论/实验课时：

- 3～4 题
- 产品基线默认 4
- 填空 >=1
- 单选 >=1
- 多选 >=1
- 判断 >=1
- 答案非空
- 解析非空
- lesson_id 非空
- 审核通过才发布

“题型覆盖检查”按钮必须调真实 API。

## 10. 实验课时介绍

每个实验课时结构化：

```text
purpose
environment
principle
steps_summary
linked_file_pack_id
linked_video_resource_id
```

原型“介绍 ✓”改为“查看介绍”，展示真实三段内容。

## 11. 完整性审计

不要写死 192。

根据当前课程动态计算：

理论：

```text
PPT
视频
题型覆盖
审核
```

实验：

```text
介绍三段
实验文件
视频
题型覆盖
```

输出：

- total
- pass
- warning
- blocking
- blocking_items
- 采购条款映射

有 blocking 时 `freeze delivery` 必须拒绝。

## 12. 采购条款映射

跨域状态只读聚合：

```text
签到 -> A
资源 -> B
投票 -> A
日志 -> E/F
知识点讲解图 -> C
实例 -> D/E
场景/DAG -> C
学情 -> F
理论/实验资源 -> B
8 类核心实验 -> B/C
```

B 不能直接读别人的业务表。

## 13. 前端

保留原型：

- KPI
- 缺项列表
- 资源流水线
- 课程蓝图
- 课时卡
- 状态/名称/类型筛选
- 新增资源
- PPT 抽检
- 视频真实时长
- 题型覆盖
- 采购映射
- 审计阻断
- 冻结交付

## 14. 权限

- 教师只管理授权课程资源
- 审核需独立 permission
- 学生只看已发布资源
- FROZEN 版本不可覆盖
- 下载走受控 URL，不用永久公网链接

## 15. 测试

必须覆盖：

- 37 lessons
- 第 7 章 4 节
- 3.6/4.2/7.4 文本
- version immutable
- 三维筛选
- 题型 coverage
- 12 个实验介绍
- manifest blocker
- freeze pass/reject
- sha256
- video duration

Playwright：

`资源总览 -> 蓝图 -> 理论 -> PPT -> 视频 -> 题库 -> 实验课时 -> 审计 -> 采购映射 -> 交付`

## 16. 不可触碰区

禁止：

- 第二套 course/lesson
- 改 class/student
- Docker/runtime
- 正式成绩
- 改 C 的 lab_definition
- 用前端布尔值假装资源已补齐

## 17. 本线验收

```text
37/37 理论课时
37/37 PPT 记录
37/37 理论视频记录且真实时长
37 个课时题库 Gate
12/12 实验课时介绍
12/12 实验文件包
12/12 实验视频
12 个实验课时题库 Gate
8 类核心映射完整
0 blocking 后才可冻结 Manifest
```

注意：**软件支持资源管理** 与 **37 个 PPT/视频实际内容已经制作完** 是两件事，完成报告必须分别说明。

## 18. 完成后给我

- commit
- migration
- 37/12 初始化方式
- API
- 审计 JSON
- Manifest JSON/XLSX
- 测试
- 仍需人工制作/上传的真实教学内容清单
