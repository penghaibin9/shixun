# F｜成绩、学情、归档与审计线：Grading + Analytics + Audit

**Codex 窗口：** F  
**工作分支：** `feat/grading-analytics`  
**前置：** P0 Event Contract 已冻结。  
**主 Gate：** G8、采购学情统计。

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

`grade_event -> grading policy -> gradebook -> 学情 -> 风险提示 -> 归档 -> 审计`

只消费 A/D/E 已发生事实，不重新制造签到/作业/实验。

## 2. 原型页面

- `page-teacher-grades`
- `page-analytics`
- `page-archive`
- `page-student-score`
- `page-admin-audit`

11 步闭环第 9/10/11 步由 F 提供真实接口，总控做编排。

## 3. 采购学情统计

### 课程总览
- 作业平均
- 测验平均
- 平均到课率
- 课程总分排行

### 按小节
- 小节选择
- 平均成绩
- 成绩分布
- 小节总分排行

### 实验双维
学生维度：

```text
实验总分
已提交
未提交
```

实验维度：

```text
实验总分/满分
已提交人数
未提交人数
```

全部真实计算，不写死。

## 4. 数据 ownership

```text
grading_policy
grading_policy_item
grade_event
gradebook
gradebook_item
student_course_score

analytics_course_summary
analytics_section_summary
analytics_student_lab_summary
analytics_lab_summary
student_risk_flag

course_archive
course_archive_artifact

audit_event
```

部分 analytics 可为物化结果，但权威事实是 grade_event + source facts。

## 5. Grade Event

```text
grade_event_id
course_id
class_id
lesson_id?
student_id
source_type
source_id
raw_score
max_score
normalized_score
occurred_at
event_id
status
```

来源：

```text
ATTENDANCE
ASSIGNMENT
QUIZ
LAB_CHECKPOINT/LAB_SUBMISSION
INTERACTION
MANUAL_ADJUSTMENT
```

event_id 唯一，重复消费不重复加分。

## 6. 成绩规则

原型默认：

```text
签到 10%
作业 20%
测验 20%
实验 40%
互动 10%
```

落为可配置 policy：

- 版本
- 生效时间
- 权重合计 100%
- 发布后锁定
- 可重算
- POSTED 后改规则必须走新版本/重新打开并审计

正式成绩只在后端算。

## 7. 事件消费

消费：

```text
attendance.completed
assignment.submitted
quiz.completed
lab.checkpoint.passed
lab.submitted
```

要求幂等、retry、错误状态、可重放。A/D/E 不得直接写 gradebook。

## 8. API

成绩：

```text
GET  /api/v1/grading/policies/{course_id}
PUT  /api/v1/grading/policies/{course_id}
POST /api/v1/grading/courses/{course_id}/recalculate
POST /api/v1/grading/courses/{course_id}/post

GET  /api/v1/gradebook/courses/{course_id}
GET  /api/v1/gradebook/courses/{course_id}/students/{student_id}
GET  /api/v1/gradebook/courses/{course_id}/trace/{student_id}
GET  /api/v1/gradebook/courses/{course_id}/export.xlsx
```

学情：

```text
GET /api/v1/analytics/courses/{course_id}/overview
GET /api/v1/analytics/courses/{course_id}/sections/{lesson_id}
GET /api/v1/analytics/courses/{course_id}/labs/by-student
GET /api/v1/analytics/courses/{course_id}/labs/by-lab
GET /api/v1/analytics/courses/{course_id}/risks
GET /api/v1/analytics/courses/{course_id}/export.xlsx
```

归档：

```text
POST /api/v1/archives/courses/{course_id}/precheck
POST /api/v1/archives/courses/{course_id}/freeze
GET  /api/v1/archives/courses/{course_id}
GET  /api/v1/archives/courses/{course_id}/manifest
```

审计：

```text
GET /api/v1/audit/events
GET /api/v1/audit/events/export.xlsx
GET /api/v1/audit/events/export.csv
```

## 9. 成绩追溯

教师点“来源”必须看到：

```text
总评
 -> 实验 40%
    -> RSA 100
       -> checkpoint results
 -> 作业
 -> 测验
 -> 签到
 -> 互动
```

每项有 source_type/source_id/time/raw/normalized/policy version。

禁止只有 86.7 没来源。

## 10. 学情计算

课程总览实际计算：

```text
avg assignment
avg quiz
attendance rate
course total ranking
```

按小节：

- section average
- 分布
- 排行

实验：

学生维：

```text
student_id
sum_lab_score
submitted_count
unsubmitted_count
```

实验维：

```text
lab_release_id
max_score
submitted_students
unsubmitted_students
avg_score
```

## 11. 风险提示

只做教学事实提示：

- 到课率低
- 连续 checkpoint fail
- 多次未交
- 总评低

每条必须有可解释事实依据，不做人格/能力判断。

## 12. 归档

Precheck：

```text
学生名单存在/冻结
成绩 POSTED
grade_event 可追溯
实验日志/判分引用存在
B 资源版本已冻结
阻断项 = 0
```

Freeze：

- gradebook lock
- resource version ref
- archive manifest
- 成绩 XLSX
- 学情 XLSX/报告数据
- 日志/判分证据引用
- course.archived event

归档不删除源数据。

## 13. 审计

`audit_event` 至少：

```text
actor_user_id
actor_role
action
resource_type
resource_id
course_id?
class_id?
student_id?
request_id
ip
result
reason
occurred_at
```

覆盖：

- 登录/越权
- 资源发布/冻结
- 实验发布
- 实例重建/销毁
- 教师协助 Terminal
- 手工改分
- 成绩入账
- 归档
- 基础设施高风险操作

普通业务接口不得 update/delete 审计。

## 14. 前端

成绩：

- 权重
- 班级结果
- 学生明细
- 来源追溯
- 重算/入账
- XLSX

学情三 tab：

```text
① 课程总览
② 按小节
③ 实验维度
```

归档：

- 门禁
- 阻断原因
- 产物
- 冻结

学生成绩只显示本人。管理员审计支持筛选/详情/导出。

## 15. XLSX

至少：

- 成绩册
- 学情总览
- 小节成绩
- 学生实验完成
- 实验完成统计
- 审计

列名稳定，带课程/班级/生成时间，不可越权导出别班。

## 16. 测试

- 同一事件重放 3 次只一条 grade_event
- 权重合计
- 重算/post/lock/trace
- 用固定 fixture 手算对比 analytics
- 缺成绩归档 block
- B 未冻结资源 block
- 全通过 archive
- archive 后不可静默改成绩
- 高风险动作有 audit
- 普通用户不可删 audit

Playwright：

`成绩 -> 重算 -> 追溯 -> 入账 -> 学情三个 tab -> 归档预检 -> 冻结 -> 学生查看本人总评`

## 17. G8

用 A/D/E 真实事实：

```text
签到
作业
测验
RSA checkpoint/submission
互动
```

完成：

`事实 -> grade_event -> gradebook -> 学情 -> 排行/分布 -> 学生查看 -> 归档`

全链可追溯。

## 18. 不可触碰区

禁止：

- 自造 attendance/assignment/runtime
- 前端算正式总评
- 改 C/D checkpoint
- 写死学情
- 删除 audit
- 归档复制无追溯新成绩

## 19. 完成后给我

- commit
- migration
- 事件消费结果
- 成绩规则
- trace 样例
- analytics 校验
- XLSX 样例
- audit coverage
- G8 PASS/FAIL
