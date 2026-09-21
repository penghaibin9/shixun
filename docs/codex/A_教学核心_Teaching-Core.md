# A｜教学核心线：Teaching Core

**Codex 窗口：** A  
**工作分支：** `feat/teaching-core`  
**前置：** P0-CONTRACT-FREEZE 已合入。  
**主 Gate：** G1、G2。

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

只负责：课程、班级、学生归班、XLSX 导学生、签到、在线投票、作业、测验、教学事件。

不负责：资源文件、Docker、实验定义、实验运行、正式成绩、学情、审计中心。

## 2. 对照原型

- `page-courses`
- `page-attendance-management`
- `page-teacher-assignments`
- `page-student-course`
- `page-student-attendance`
- `page-student-quiz`
- `page-lifecycle` 第 1、2、4、5、8 步的真实能力
- 给 `teacher-dashboard / student-home` 提供 ReadModel API，但不改总控页面

## 3. 采购条款

### 签到
必须支持：

- 在线发布
- 设置有效时间
- 签到链接
- 实时/历史结果
- 按小节查看在线作业签到/考试签到
- 类型：课堂/实验/在线作业/考试
- 应到/实到/迟到/未到
- XLSX 导出

### 在线投票
三种：

```text
理解度投票
作业完成情况
教学反馈
```

统计维度随 poll_type 变化，不写死前端。

## 4. 数据表 ownership

```text
course
course_chapter
course_lesson
class
class_course
class_membership
teaching_teacher_assignment

attendance_task
attendance_record

poll
poll_option
poll_answer

assignment
assignment_question_ref
assignment_submission

quiz
quiz_question_ref
quiz_attempt
quiz_answer
```

约束：

- `course_lesson` 是统一 lesson 事实。
- `class_membership` 是唯一学生归班关系。
- assignment/quiz 引用 B 的 `question_id`，发布时可保存题目版本快照用于历史追溯，但不能造第二题库。

## 5. API

```text
POST   /api/v1/courses
GET    /api/v1/courses
GET    /api/v1/courses/{course_id}
PATCH  /api/v1/courses/{course_id}

POST   /api/v1/classes
GET    /api/v1/classes
GET    /api/v1/classes/{class_id}

GET    /api/v1/classes/{class_id}/members
POST   /api/v1/classes/{class_id}/members/import
GET    /api/v1/classes/{class_id}/members/import-template
GET    /api/v1/import-jobs/{job_id}
GET    /api/v1/import-jobs/{job_id}/error-rows.xlsx

POST   /api/v1/attendance/tasks
GET    /api/v1/attendance/tasks
GET    /api/v1/attendance/tasks/{id}
POST   /api/v1/attendance/tasks/{id}/publish
POST   /api/v1/attendance/tasks/{id}/close
GET    /api/v1/attendance/tasks/{id}/records
GET    /api/v1/attendance/section-summary
POST   /api/v1/attendance/{id}/sign
GET    /api/v1/attendance/{id}/export.xlsx

POST   /api/v1/polls
POST   /api/v1/polls/{id}/publish
POST   /api/v1/polls/{id}/answers
GET    /api/v1/polls/{id}/results

POST   /api/v1/assignments
POST   /api/v1/assignments/{id}/publish
POST   /api/v1/assignments/{id}/submit

POST   /api/v1/quizzes
POST   /api/v1/quizzes/{id}/publish
POST   /api/v1/quizzes/{id}/attempts
POST   /api/v1/quizzes/{id}/attempts/{attempt_id}/submit
```

## 6. XLSX 导学生必须做真

模板至少：

```text
学号*
姓名*
班级
手机号（可选）
邮箱（可选）
```

校验：

- 空学号/姓名
- 学号重复
- membership 重复
- 超长值
- 公式单元格风险
- 空白行
- 批次重复提交

结果：

- 成功/失败/重复数量
- 逐行错误原因
- `error_rows.xlsx`
- 导入审计

43 人用于测试 fixture/seed，禁止写死业务代码。

## 7. 签到细节

```text
attendance_task:
  course_id
  class_id
  lesson_id
  task_type
  title
  starts_at
  expires_at
  sign_token_hash
  status

attendance_record:
  task_id
  student_id
  signed_at
  result
  source
```

签到链接用不可预测 token，不暴露自增 ID。同学生同 task 只能一条有效记录。

按小节必须返回：

```text
lesson
签到类型
应到
实到
迟到
缺勤
状态
```

## 8. 投票

`poll_type`：

```text
UNDERSTANDING
ASSIGNMENT_COMPLETION
TEACHING_FEEDBACK
```

结果必须后端真实统计。

## 9. 作业/测验

- 题来自 B question bank。
- 发布时锁定 question version/snapshot。
- A 产生原始 submission/attempt 分数事实。
- 正式课程总评由 F 计算。
- 支持截止、班级、随机题序、限时。
- 学生只可提交本人任务。

## 10. 事件输出

```text
attendance.completed
poll.completed
assignment.submitted
quiz.completed
```

payload 至少带：

```text
course_id
class_id
lesson_id
student_id
source_id
raw_score/max_score（适用时）
```

## 11. 前端

还原原型：

- 课程卡片/章节/班级学生数
- 签到发布、复制链接、KPI、历史台账、按小节详情、类型过滤、XLSX
- 三种投票切换和不同统计
- 教师发布作业/测验
- 学生签到/作答/提交

select/check/radio 统一用公共 Yk 组件。

## 12. 权限必测

- 教师 A 访问教师 B 班 -> deny
- 学生 A 访问学生 B 数据 -> deny
- 学生不可发布签到
- 关闭签到不可重复签到
- permission 通过 UserContext，不硬编码 `if role == teacher`

## 13. 测试

后端：

- course/class
- membership import/idempotency
- attendance time window/duplicate/section summary
- poll 三模式
- assignment/quiz publish/submit
- 越权

Playwright 主链：

```text
教师登录
-> 建课程
-> 建班
-> XLSX 导 43 人
-> 发布签到
-> 学生签到
-> 教师看到结果
-> 发布投票
-> 学生作答
-> 发布作业/测验
-> 学生提交
```

## 14. 不可触碰区

禁止修改：

```text
resources/*
labs/*
lab_runtime/*
infrastructure/*
grading/*
analytics/*
audit/*
node_agent/*
```

禁止自己创建 Docker、计算正式总评、自建题库、自建学生表。

## 15. Gate

### G1
全新 MySQL：

`课程 -> 班级 -> 下载模板 -> XLSX 导 43 人 -> 错误行反馈 -> 名单回读`

### G2
`教师发布签到 -> 学生真实登录 -> 签到 -> 教师实时/历史/按小节查看`

另验收三类投票、作业/测验、事件 outbox、跨班隔离。

## 16. 完成后给我

- commit
- migration
- API
- XLSX 模板与错误行样本
- pytest/MySQL/frontend/Playwright
- G1/G2 PASS/FAIL
- 与其他线的剩余联调点
