# B 实验文件包验收证据

更新时间：2026-09-22

## 结论

- 12 套实验文件包：PASS（通过）。
- 系统上传、版本、独立审核、发布和课时关联：PASS（通过）。
- 外部教研专家人工验收：NOT RUN（未运行）。
- 本文记录实验文件包专项完成时的历史分项结果；后续 37 份 PPT（演示文稿）和 49 个视频已经补齐，当前 B 课程资源联合动态审计为 196/196、阻断 0，详见 `docs/acceptance/b-course-resources-evidence.md`。

## 实物与映射

| 课时 | 文件包 | 核心验证 |
|---|---|---|
| 实验01 | `lab01-aes-des-basics-v1.zip` | AES（高级加密标准）回环与 DES（数据加密标准）遗留限制 |
| 实验02 | `lab02-ecb-cbc-comparison-v1.zip` | ECB（电子密码本模式）/CBC（密码分组链接模式）分组重复特征 |
| 实验03 | `lab03-rsa-encryption-v1.zip` | RSA（非对称加密算法）密钥生成与加解密 |
| 实验04 | `lab04-digital-signature-v1.zip` | 数字签名正向与篡改反向验证 |
| 实验05 | `lab05-file-hash-v1.zip` | SHA-256（256位安全哈希算法）完整性基线 |
| 实验06 | `lab06-base64-text-v1.zip` | UTF-8（8位统一字符编码格式）与 Base64（基础64编码）回环 |
| 实验07 | `lab07-lsb-steganography-v1.zip` | LSB（最低有效位）隐写与提取 |
| 实验08 | `lab08-database-rbac-v1.zip` | RBAC（基于角色的访问控制）数据库权限包 |
| 实验09 | `lab09-data-masking-v1.zip` | 手机号、身份证号脱敏 |
| 实验10 | `lab10-backup-restore-v1.zip` | 全量/增量备份与校验恢复 |
| 实验11 | `lab11-log-audit-v1.zip` | 日志解析和异常规则 |
| 实验12 | `lab12-governance-v1.zip` | 数据资产、风险、控制和整改闭环 |

统一交付目录为 `outputs/01a0c33f-d483-7ac0-aa95-632194b582d5/lab-file-packs-v1`。`index.json` 登记文件名、课时、压缩包大小、文件数、SHA256（文件校验值）与验证命令；每个压缩包内含 `README.md`、`NOTICE.txt` 和 `pack-manifest.json`。

## 已验证

1. `scripts/build-lab-file-packs.py` 可由版本化内容源稳定重建全部文件包。
2. `archive_file_count` 在创建版本前检查损坏包、路径穿越、绝对路径、链接、设备文件、加密条目、条目数与解压大小。
3. `backend/tests/test_formal_lab_file_packs_mysql.py` 使用真实 MySQL（关系型数据库）逐包完成上传、版本、提交审核、制作者自审拒绝、独立审核、发布、下载和课时关联。
4. `tests/verify_lab_file_packs.py` 在固定镜像 `python@sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca` 中断网执行全部验证命令，12/12 通过。
5. `tests/seed_lab_file_packs.py` 只允许写入 `yueke_question_bank_content_v101_dev` 隔离开发库；发现同课时重复资源或内容不一致时拒绝覆盖。

## 动态审计

本专项当时与正式 196 题合并后的课程审计为 73/196 项通过、123 项阻断，实验文件就绪度为 12/12。该数值是阶段性历史证据；后续内容已补齐，当前联合结果以总证据文档中的 196/196 为准。
