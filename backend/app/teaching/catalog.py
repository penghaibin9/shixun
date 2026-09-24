from uuid import NAMESPACE_URL, uuid5

from app.contentpacks.catalog import load_bundled_course_pack


COURSE_ID = "course_data_security"
DEFAULT_CATALOG_KEY = "data_security_v1"
WEB_SECURITY_CATALOG_KEY = "web_security_v1"

THEORY_LESSONS = [
    (1, "1.1", "数据基础：定义、特征、分类与全生命周期"),
    (1, "1.2", "典型数据处理场景：开发利用、共享交易、跨境流动"),
    (1, "1.3", "数据安全概念与三要素"),
    (1, "1.4", "数据安全威胁分析：黑客攻击、恶意软件、社工攻击、物联网安全"),
    (1, "1.5", "数据安全法律法规与合规要求"),
    (2, "2.1", "数据分类的概念、目的、原则、方法与流程"),
    (2, "2.2", "数据分级的概念、目的、标准与实施流程"),
    (2, "2.3", "数据分类分级实践案例"),
    (3, "3.1", "对称加密算法：AES、DES 原理与加密模式"),
    (3, "3.2", "非对称加密算法：RSA 密钥生成、加解密与数字签名"),
    (3, "3.3", "哈希算法与完整性校验：MD5、SHA 系列"),
    (3, "3.4", "国密算法体系：SM2、SM3、SM4"),
    (3, "3.5", "数据编码：Base64 等编码方法"),
    (3, "3.6", "数据存储加密（内容加密/磁盘加密）与传输加密（信源加密/通道加密）"),
    (4, "4.1", "敏感数据定义与自动识别方法"),
    (4, "4.2", "经典脱敏算法（替换/仿真/加密/遮掩/混淆/偏移/取整）"),
    (4, "4.3", "数据匿名化算法：K 匿名、T 相近"),
    (4, "4.4", "静态脱敏与动态脱敏的对比与应用"),
    (4, "4.5", "身份标识与认证机制"),
    (4, "4.6", "权限管理方法与 RBAC 访问控制模型"),
    (4, "4.7", "数据库访问控制实例与越权访问防范"),
    (5, "5.1", "数字水印基本原理与工作流程"),
    (5, "5.2", "水印嵌入算法与提取算法：盲水印 / 非盲水印"),
    (5, "5.3", "水印应用场景：版权保护、身份验证、内容追踪、隐私保护"),
    (5, "5.4", "隐私计算导论：差分隐私、安全多方计算"),
    (5, "5.5", "同态加密与联邦学习"),
    (5, "5.6", "数据审计体系：数据库、应用、主机、网络审计"),
    (5, "5.7", "审计日志管理与异常访问行为溯源分析"),
    (6, "6.1", "数据容灾备份概念与核心指标：RPO / RTO"),
    (6, "6.2", "灾备级别与灾备方案设计：双活、灾备、两地三中心"),
    (6, "6.3", "数据销毁分类：物理销毁法与逻辑销毁法"),
    (6, "6.4", "网络数据销毁技术：密钥销毁 / 时间过期自销毁"),
    (6, "6.5", "全量备份与增量备份策略"),
    (7, "7.1", "数据安全治理的概念、目标与体系框架"),
    (7, "7.2", "数据安全治理流程与方法"),
    (7, "7.3", "行业数据安全治理实践（医疗/政务/工业领域案例）"),
    (7, "7.4", "典型数据安全产品选型指南（加密类/脱敏类/审计类/管控类/备份类）"),
]

LAB_LESSONS = [
    ("01", "AES/DES", "AES/DES 基础加解密"),
    ("02", "AES/DES", "ECB/CBC 模式对比"),
    ("03", "RSA", "RSA 密钥生成与加解密"),
    ("04", "RSA", "数字签名生成与验证"),
    ("05", "MD5/SHA", "文件哈希与完整性校验"),
    ("06", "Base64/隐写", "Base64 与文本编码"),
    ("07", "Base64/隐写", "LSB 图片隐写与提取"),
    ("08", "数据库权限", "用户、角色与权限配置"),
    ("09", "数据脱敏", "手机号/身份证脱敏规则"),
    ("10", "备份与灾难恢复", "全量/增量备份与恢复"),
    ("11", "日志审计与溯源", "日志抓取、解析与异常识别"),
    ("12", "综合实践", "数据安全治理综合实践"),
]

CHAPTER_TITLES = {
    1: "数据安全基础",
    2: "数据资产分类分级",
    3: "数据加密与完整性保护",
    4: "数据脱敏与访问管控",
    5: "数据溯源与隐私保护",
    6: "数据灾备与安全销毁",
    7: "数据安全治理实践",
}


def _stable_id(course_id: str, kind: str, key: str) -> str:
    if course_id == COURSE_ID and kind == "lesson":
        return key
    return str(uuid5(NAMESPACE_URL, f"yueke:{course_id}:{kind}:{key}"))


def _data_security_curriculum_rows(course_id: str = COURSE_ID) -> dict[str, list[dict]]:
    chapters = [
        {
            "chapter_id": _stable_id(course_id, "chapter", str(chapter_no)),
            "course_id": course_id,
            "title": CHAPTER_TITLES[chapter_no],
            "sequence": chapter_no,
        }
        for chapter_no in range(1, 8)
    ]
    chapters.append(
        {
            "chapter_id": _stable_id(course_id, "chapter", "lab"),
            "course_id": course_id,
            "title": "实验课程",
            "sequence": 8,
        }
    )
    chapter_ids = {row["sequence"]: row["chapter_id"] for row in chapters}
    lessons = [
        {
            "lesson_id": _stable_id(course_id, "lesson", f"lesson_theory_{code.replace('.', '_')}"),
            "course_id": course_id,
            "chapter_id": chapter_ids[chapter],
            "lesson_code": code,
            "title": title,
            "sequence": int(code.split(".")[1]),
            "lesson_type": "THEORY",
        }
        for chapter, code, title in THEORY_LESSONS
    ]
    lessons.extend(
        {
            "lesson_id": _stable_id(course_id, "lesson", f"lesson_lab_{code}"),
            "course_id": course_id,
            "chapter_id": chapter_ids[8],
            "lesson_code": f"实验{code}",
            "title": title,
            "sequence": int(code),
            "lesson_type": "LAB",
        }
        for code, _, title in LAB_LESSONS
    )
    return {"chapters": chapters, "lessons": lessons}


def _web_security_curriculum_rows(course_id: str) -> dict[str, list[dict]]:
    pack = load_bundled_course_pack("web-security-v1.json")
    chapters = [
        {
            "chapter_id": _stable_id(course_id, "chapter", "web-theory"),
            "course_id": course_id,
            "title": "Web 安全理论",
            "sequence": 1,
        },
        {
            "chapter_id": _stable_id(course_id, "chapter", "web-labs"),
            "course_id": course_id,
            "title": "Web 安全实验",
            "sequence": 2,
        },
    ]
    chapter_by_type = {"THEORY": chapters[0]["chapter_id"], "LAB": chapters[1]["chapter_id"]}
    lessons = []
    for item in pack.lessons:
        if item.lesson_type == "THEORY":
            sequence = int(item.lesson_code.split(".", 1)[1])
        else:
            digits = "".join(character for character in item.lesson_code if character.isdigit())
            sequence = int(digits)
        lessons.append(
            {
                "lesson_id": _stable_id(course_id, "lesson", f"web:{item.lesson_code}"),
                "course_id": course_id,
                "chapter_id": chapter_by_type[item.lesson_type],
                "lesson_code": item.lesson_code,
                "title": item.title,
                "sequence": sequence,
                "lesson_type": item.lesson_type,
            }
        )
    return {"chapters": chapters, "lessons": lessons}


def curriculum_rows(course_id: str = COURSE_ID, catalog_key: str = DEFAULT_CATALOG_KEY) -> dict[str, list[dict]]:
    if catalog_key == DEFAULT_CATALOG_KEY:
        return _data_security_curriculum_rows(course_id)
    if catalog_key == WEB_SECURITY_CATALOG_KEY:
        return _web_security_curriculum_rows(course_id)
    raise ValueError(f"未知课程模板：{catalog_key}")


def catalog_metadata() -> list[dict[str, str | int]]:
    return [
        {
            "catalog_key": DEFAULT_CATALOG_KEY,
            "name": "数据安全技术基础",
            "theory_lessons": len(THEORY_LESSONS),
            "lab_lessons": len(LAB_LESSONS),
        },
        {
            "catalog_key": WEB_SECURITY_CATALOG_KEY,
            "name": "Web 应用安全实训",
            "theory_lessons": 12,
            "lab_lessons": 12,
        },
    ]


def lesson_id_by_code(course_id: str = COURSE_ID, catalog_key: str = DEFAULT_CATALOG_KEY) -> dict[str, str]:
    return {row["lesson_code"]: row["lesson_id"] for row in curriculum_rows(course_id, catalog_key)["lessons"]}
