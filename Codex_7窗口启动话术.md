# Codex 7 窗口启动话术

## 窗口 0｜总控

```text
先读取根目录 AGENTS.md，再读取 docs/codex/00_总控集成_P0-CONTRACT-FREEZE.md。
把后者作为本窗口唯一施工任务书。
先扫描当前仓库并复用现有代码，然后直接执行 P0-CONTRACT-FREEZE。
不要只给方案，要实际修改代码、migration、contract、公共组件和测试。
完成后提交本地 Git，并按 AGENTS.md 的最终回复格式给我结果。
```

---

## 窗口 A｜教学核心

```text
先读取根目录 AGENTS.md，再读取 docs/codex/A_教学核心_Teaching-Core.md。
本窗口只负责 A teaching-core，严格遵守 ownership 和不可触碰区。
先审计现有代码，能复用就复用，然后直接施工到 G1、G2 可验收。
不要只输出说明，实际修改前后端、MySQL migration、XLSX、权限、测试。
完成后提交本工作树分支并报告 Gate。
```

## 窗口 B｜课程资源

```text
先读取根目录 AGENTS.md，再读取 docs/codex/B_课程资源_Course-Resources.md。
本窗口只负责 B course-resources。
必须以最终 HTML 的 37 理论课时 + 12 实验课时为准，不得退回旧 36 课时。
直接施工真实资源、版本、题库、审计、Manifest 和测试，不要只写方案。
完成后提交本工作树分支并报告采购资源门禁。
```

## 窗口 C｜实验定义

```text
先读取根目录 AGENTS.md，再读取 docs/codex/C_实验定义_Lab-Designer.md。
本窗口只负责 C lab-designer。
牢记：C 只定义实验，不操作 Docker。
优先把 RSA 的版本化定义、拓扑、DAG、5 个 checkpoint、判定规则和 G3 做实。
完成后提交本工作树分支并报告 G3。
```

## 窗口 D｜实验运行底座

```text
先读取根目录 AGENTS.md，再读取 docs/codex/D_实验运行底座_Lab-Runtime.md。
本窗口只负责 D lab-runtime / infrastructure。
这是本项目最关键施工线：必须做真实 Linux Docker、Node Agent、网络隔离、Web Terminal、RSA 真命令、真 checkpoint、销毁和恢复。
禁止用 mock 当 G4/G5/G6 证据。
直接施工并测试，完成后提交本工作树分支并报告真实 Gate。
```

## 窗口 E｜实验课堂

```text
先读取根目录 AGENTS.md，再读取 docs/codex/E_实验课堂_Lab-Classroom.md。
本窗口只负责 E lab-classroom / teaching-logs。
E 只能调用 D 的 runtime contract，禁止自己 docker run。
把教师 43 人运行中心、学生实验、Terminal 前端、异常处置、审计/流量日志下载和指定学生分发做实。
完成后提交本工作树分支并报告 G5 前端链路和 G7。
```

## 窗口 F｜成绩学情审计

```text
先读取根目录 AGENTS.md，再读取 docs/codex/F_成绩学情审计_Grading-Analytics-Audit.md。
本窗口只负责 F grading / analytics / audit / archive。
只消费 A/D/E 的真实事实事件，禁止重新制造签到、作业、实验事实，禁止前端临时算正式成绩。
把 grade_event -> gradebook -> 三个学情 Tab -> XLSX -> 归档 -> audit 做实。
完成后提交本工作树分支并报告 G8。
```
