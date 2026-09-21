import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { Presentation, PresentationFile } from "@oai/artifact-tool";


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceDir = path.resolve(scriptDir, "..");
const skillDir = process.env.YUEKE_PRESENTATION_SKILL_DIR;
const runtimePython = process.env.YUEKE_PRESENTATION_PYTHON;
if (!skillDir || !path.isAbsolute(skillDir) || !runtimePython || !path.isAbsolute(runtimePython)) {
  throw new Error("YUEKE_PRESENTATION_SKILL_DIR and YUEKE_PRESENTATION_PYTHON must be absolute paths");
}

const sourcePath = path.join(workspaceDir, "backend", "app", "resources", "content", "theory-ppts-v1.json");
const coverPath = path.join(workspaceDir, "backend", "app", "resources", "content", "assets", "data-security-cover-v1.png");
const outputDir = process.env.YUEKE_PPT_OUTPUT_DIR
  ? path.resolve(process.env.YUEKE_PPT_OUTPUT_DIR)
  : path.join(workspaceDir, "outputs", "01a0c33f-d483-7ac0-aa95-632194b582d5", "theory-ppts-v1");
const buildDir = process.env.YUEKE_PPT_BUILD_DIR
  ? path.resolve(process.env.YUEKE_PPT_BUILD_DIR)
  : path.join(workspaceDir, "backend", "var", "theory-ppt-build-v1");

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools", "artifact_tool_utils.mjs")).href,
);

const data = JSON.parse(await fs.readFile(sourcePath, "utf8"));
const coverBytes = new Uint8Array(await fs.readFile(coverPath));
if (data.courseId !== "course_data_security" || data.version !== "1.0.0" || data.lessons.length !== 37) {
  throw new Error("Theory PPT source must contain exactly 37 lessons for course_data_security version 1.0.0");
}
if (new Set(data.lessons.map((item) => item.lessonId)).size !== 37) {
  throw new Error("Theory PPT lesson identifiers must be unique");
}

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(buildDir, { recursive: true });
const existing = await fs.readdir(outputDir);
if (existing.length) {
  throw new Error(`Output directory must be empty: ${outputDir}`);
}

const FONT = "Microsoft YaHei";
const COLORS = {
  navy: "#10213F",
  primary: "#2457F5",
  primaryDark: "#1846CD",
  pale: "#F5F7FB",
  text: "#172033",
  muted: "#667085",
  white: "#FFFFFF",
  green: "#149968",
  lightBlue: "#DCE7FF",
};
const slideSize = { width: 1280, height: 720 };
const expectedSlideSizeEmu = "12192000,6858000";

const visibleTermExpansions = [
  [/\bSHA-256\b(?!（)/g, "SHA-256（256位安全散列算法）"],
  [/\bAES\b(?![-\w]|（)/g, "AES（高级加密标准）"],
  [/\bDES\b(?![-\w]|（)/g, "DES（数据加密标准）"],
  [/\bRSA\b(?![-\w]|（)/g, "RSA（非对称加密算法）"],
  [/\bMD5\b(?![-\w]|（)/g, "MD5（消息摘要算法第5版）"],
  [/\bSHA\b(?![-\w]|（)/g, "SHA（安全散列算法）"],
  [/\bSM2\b(?![-\w]|（)/g, "SM2（国密公钥算法）"],
  [/\bSM3\b(?![-\w]|（)/g, "SM3（国密杂凑算法）"],
  [/\bSM4\b(?![-\w]|（)/g, "SM4（国密分组密码算法）"],
  [/\bBase64\b(?![-\w]|（)/g, "Base64（基础64编码）"],
  [/\bRBAC\b(?![-\w]|（)/g, "RBAC（基于角色的访问控制）"],
  [/\bECB\b(?![-\w]|（)/g, "ECB（电子密码本模式）"],
  [/\bCBC\b(?![-\w]|（)/g, "CBC（密码分组链接模式）"],
  [/\bTLS\b(?![-\w]|（)/g, "TLS（传输层安全协议）"],
  [/\bHTTPS\b(?![-\w]|（)/g, "HTTPS（超文本传输安全协议）"],
  [/\bIoT\b(?![-\w]|（)/g, "IoT（物联网）"],
  [/\bMFA\b(?![-\w]|（)/g, "MFA（多因素认证）"],
  [/\bMPC\b(?![-\w]|（)/g, "MPC（安全多方计算）"],
  [/\bPoC\b(?![-\w]|（)/g, "PoC（概念验证）"],
  [/\bRPO\b(?![-\w]|（)/g, "RPO（恢复点目标）"],
  [/\bRTO\b(?![-\w]|（)/g, "RTO（恢复时间目标）"],
  [/\bUTF-8\b(?![-\w]|（)/g, "UTF-8（8位统一字符编码格式）"],
  [/\bIETF\b(?![-\w]|（)/g, "IETF（互联网工程任务组）"],
  [/\bRFC\b(?![-\w]|（)/g, "RFC（征求意见稿标准）"],
  [/\bNIST\b(?![-\w]|（)/g, "NIST（美国国家标准与技术研究院）"],
  [/\bFIPS\b(?![-\w]|（)/g, "FIPS（联邦信息处理标准）"],
  [/\bSP\b(?![-\w]|（)/g, "SP（特别出版物）"],
];

function localizeVisible(value) {
  return visibleTermExpansions.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), String(value));
}

function addText(slide, text, position, options = {}) {
  const box = slide.shapes.add({
    geometry: "textbox",
    position,
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  box.text = localizeVisible(text);
  box.text.style = {
    typeface: FONT,
    fontSize: options.fontSize ?? 24,
    bold: options.bold ?? false,
    color: options.color ?? COLORS.text,
    autoFit: "none",
  };
  return box;
}

function referenceNotes(lesson, context) {
  const references = lesson.references
    .map((item, index) => `${index + 1}. ${localizeVisible(item.title)}\n${item.url}`)
    .join("\n");
  return `${context}\n\n资料来源：\n${references}\n\n版权说明：课件文字为项目原创教学编排；封面抽象图由图像生成工具为本项目生成，不代表真实系统、设备或现场。`;
}

function addFooter(slide, lesson, pageNumber, dark = false) {
  addText(
    slide,
    `${lesson.lessonCode}  数据安全技术基础`,
    { left: 64, top: 674, width: 560, height: 24 },
    { fontSize: 12, color: dark ? COLORS.lightBlue : COLORS.muted },
  );
  addText(
    slide,
    `${String(pageNumber).padStart(2, "0")}  来源与版权信息见演讲者备注`,
    { left: 760, top: 674, width: 456, height: 24 },
    { fontSize: 12, color: dark ? COLORS.lightBlue : COLORS.muted },
  );
}

function addCover(presentation, lesson) {
  const slide = presentation.slides.add();
  slide.background.fill = COLORS.navy;
  slide.images.add({
    blob: coverBytes,
    contentType: "image/png",
    alt: "抽象的数据安全分层防护与可信流转主视觉",
    fit: "cover",
    position: { left: 0, top: 0, width: slideSize.width, height: slideSize.height },
  });
  addText(slide, `第 ${lesson.lessonCode.split(".")[0]} 章  ·  ${lesson.lessonCode}`, { left: 70, top: 90, width: 520, height: 44 }, { fontSize: 18, bold: true, color: COLORS.lightBlue });
  addText(slide, lesson.title, { left: 70, top: 170, width: 600, height: 270 }, { fontSize: 42, bold: true, color: COLORS.white });
  addText(slide, "数据安全技术基础", { left: 70, top: 516, width: 420, height: 48 }, { fontSize: 24, color: COLORS.lightBlue });
  addText(slide, "跃科网络空间安全实训平台", { left: 70, top: 586, width: 430, height: 32 }, { fontSize: 16, color: COLORS.lightBlue });
  slide.speakerNotes.textFrame.setText(referenceNotes(lesson, "封面。说明本课在课程蓝图中的位置，并用一个真实业务问题导入主题。"));
}

function addOverview(presentation, lesson) {
  const slide = presentation.slides.add();
  slide.background.fill = COLORS.pale;
  addText(slide, "本课目标与知识结构", { left: 64, top: 46, width: 920, height: 58 }, { fontSize: 34, bold: true });
  addText(slide, lesson.lessonCode, { left: 1040, top: 38, width: 176, height: 70 }, { fontSize: 42, bold: true, color: COLORS.primary });
  addText(slide, "学习目标", { left: 72, top: 150, width: 420, height: 38 }, { fontSize: 20, bold: true, color: COLORS.primaryDark });
  addText(
    slide,
    lesson.learningObjectives.map((value, index) => `${String(index + 1).padStart(2, "0")}  ${value}`).join("\n\n"),
    { left: 72, top: 210, width: 500, height: 340 },
    { fontSize: 24 },
  );
  addText(slide, "知识结构", { left: 650, top: 150, width: 420, height: 38 }, { fontSize: 20, bold: true, color: COLORS.primaryDark });
  addText(
    slide,
    lesson.conceptSlides.map((value, index) => `${String(index + 1).padStart(2, "0")}  ${value.title}`).join("\n\n"),
    { left: 650, top: 210, width: 540, height: 380 },
    { fontSize: 22 },
  );
  addFooter(slide, lesson, 2);
  slide.speakerNotes.textFrame.setText(referenceNotes(lesson, "学习目标与知识结构。先说明目标，再解释各知识点之间的依赖关系。"));
}

function addConcept(presentation, lesson, concept, index, pageNumber) {
  const slide = presentation.slides.add();
  slide.background.fill = index % 2 === 0 ? COLORS.white : COLORS.pale;
  addText(slide, `${String(index + 1).padStart(2, "0")}  核心概念`, { left: 66, top: 46, width: 350, height: 34 }, { fontSize: 17, bold: true, color: COLORS.primary });
  addText(slide, concept.title, { left: 66, top: 106, width: 1030, height: 82 }, { fontSize: 36, bold: true });
  addText(slide, concept.explanation, { left: 66, top: 222, width: 1140, height: 126 }, { fontSize: 25, color: COLORS.text });
  addText(
    slide,
    concept.points.map((value, pointIndex) => `${String(pointIndex + 1).padStart(2, "0")}  ${value}`).join("\n\n"),
    { left: 84, top: 390, width: 1090, height: 226 },
    { fontSize: 20, color: COLORS.muted },
  );
  addFooter(slide, lesson, pageNumber);
  slide.speakerNotes.textFrame.setText(referenceNotes(lesson, `核心概念：${concept.title}。结合要点解释定义、适用边界和验证方式。`));
}

function addCase(presentation, lesson, pageNumber) {
  const slide = presentation.slides.add();
  slide.background.fill = COLORS.pale;
  addText(slide, "业务案例", { left: 66, top: 46, width: 300, height: 44 }, { fontSize: 20, bold: true, color: COLORS.primary });
  addText(slide, "把概念放回真实决策", { left: 66, top: 108, width: 900, height: 70 }, { fontSize: 36, bold: true });
  addText(slide, lesson.caseExample, { left: 66, top: 224, width: 1140, height: 176 }, { fontSize: 27 });
  addText(slide, "课堂讨论", { left: 66, top: 446, width: 260, height: 34 }, { fontSize: 19, bold: true, color: COLORS.primaryDark });
  addText(
    slide,
    `01  案例中的核心数据资产、威胁和责任主体分别是什么？\n\n02  优先控制措施是什么，如何用日志、测试或指标验证效果？\n\n03  哪些边界条件变化后，需要重新评估方案？`,
    { left: 66, top: 496, width: 1130, height: 140 },
    { fontSize: 19, color: COLORS.muted },
  );
  addFooter(slide, lesson, pageNumber);
  slide.speakerNotes.textFrame.setText(referenceNotes(lesson, "业务案例。引导学生先识别事实，再提出控制方案和可验证证据。"));
}

function addKnowledgeCheck(presentation, lesson, pageNumber) {
  const slide = presentation.slides.add();
  slide.background.fill = COLORS.navy;
  addText(slide, "知识检查", { left: 66, top: 48, width: 300, height: 44 }, { fontSize: 20, bold: true, color: COLORS.lightBlue });
  addText(slide, lesson.knowledgeCheck.question, { left: 66, top: 142, width: 1130, height: 176 }, { fontSize: 34, bold: true, color: COLORS.white });
  addText(slide, "参考答案", { left: 66, top: 390, width: 260, height: 36 }, { fontSize: 19, bold: true, color: COLORS.green });
  addText(slide, lesson.knowledgeCheck.answer, { left: 66, top: 452, width: 1130, height: 160 }, { fontSize: 24, color: COLORS.lightBlue });
  addFooter(slide, lesson, pageNumber, true);
  slide.speakerNotes.textFrame.setText(referenceNotes(lesson, "知识检查。先让学生独立回答，再展示参考答案并回到本课学习目标。"));
}

const index = {
  schema_version: "1.0",
  content_version: data.version,
  course_id: data.courseId,
  deck_count: 37,
  slide_total: 0,
  visual_style: "prototype/current.html blue-white teaching theme",
  font: FONT,
  decks: [],
};

for (const lesson of data.lessons) {
  if (!lesson.conceptSlides || lesson.conceptSlides.length < 3 || lesson.conceptSlides.length > 5) {
    throw new Error(`${lesson.lessonCode} must contain 3 to 5 concept slides`);
  }
  const presentation = Presentation.create({ slideSize });
  addCover(presentation, lesson);
  addOverview(presentation, lesson);
  lesson.conceptSlides.forEach((concept, conceptIndex) => {
    addConcept(presentation, lesson, concept, conceptIndex, conceptIndex + 3);
  });
  addCase(presentation, lesson, lesson.conceptSlides.length + 3);
  addKnowledgeCheck(presentation, lesson, lesson.conceptSlides.length + 4);

  const slideCount = lesson.conceptSlides.length + 4;
  const codePart = lesson.lessonCode.split(".").map((part) => part.padStart(2, "0")).join("-");
  const filename = `theory-${codePart}-v1.pptx`;
  const finalPath = path.join(outputDir, filename);
  const stagingDir = path.join(buildDir, codePart);
  await fs.mkdir(stagingDir, { recursive: true });
  const candidatePath = path.join(stagingDir, "candidate.pptx");
  await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

  await finalizePresentation({
    explicitTotalSlideCount: slideCount,
    requiredNativeTableOwnerSlides: [],
    requiredNativeChartOwnerSlides: [],
    workspaceDir,
    candidatePath,
    finalPath,
    pythonExecutable: runtimePython,
    integrityValidatorPath: path.join(skillDir, "container_tools", "inspect_presentation_package_integrity.py"),
    layoutValidatorPath: path.join(skillDir, "container_tools", "inspect_presentation_layout_geometry.py"),
    layoutArgs: ["--expected-slide-size-emu", expectedSlideSizeEmu, "--validate-heading-fit"],
    fontPolicy: { basis: "design", families: [FONT] },
    verifyArtifactToolImport: true,
    receiptPath: path.join(stagingDir, `${filename}.validation.json`),
  });

  const fileBytes = await fs.readFile(finalPath);
  index.slide_total += slideCount;
  index.decks.push({
    lesson_id: lesson.lessonId,
    lesson_code: lesson.lessonCode,
    chapter_no: Number(lesson.lessonCode.split(".")[0]),
    title: lesson.title,
    display_title: localizeVisible(lesson.title),
    filename,
    slide_count: slideCount,
    size_bytes: fileBytes.length,
    sha256: crypto.createHash("sha256").update(fileBytes).digest("hex"),
    source_count: lesson.references.length,
    quality_design: {
      knowledge_complete: true,
      layout_overflow_validated: true,
      animation_count: 0,
      copyright_noted: true,
    },
  });
}

await fs.writeFile(path.join(outputDir, "index.json"), `${JSON.stringify(index, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ output_dir: outputDir, deck_count: index.deck_count, slide_total: index.slide_total }, null, 2));
