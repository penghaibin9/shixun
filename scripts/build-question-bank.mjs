import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "..");
const sourcePath = path.join(projectRoot, "backend", "app", "resources", "content", "question-bank-v1.json");
const outputDir = path.join(projectRoot, "outputs", "01a0c33f-d483-7ac0-aa95-632194b582d5");
const outputPath = path.join(outputDir, "question-bank-196-v1.xlsx");

const HEADERS = ["课时标识*", "课时编号", "题型*", "题干*", "选项A", "选项B", "选项C", "选项D", "正确答案*", "解析*"];
const TYPE_ORDER = ["填空", "单选", "多选", "判断"];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function validateBank(bank) {
  assert(bank.courseId === "course_data_security", "课程标识不正确");
  assert(bank.lessons.length === 49, `课时必须为49个，当前为${bank.lessons.length}个`);
  const lessonIds = new Set();
  const lessonCodes = new Set();
  for (const lesson of bank.lessons) {
    assert(!lessonIds.has(lesson.lessonId), `课时标识重复：${lesson.lessonId}`);
    assert(!lessonCodes.has(lesson.lessonCode), `课时编号重复：${lesson.lessonCode}`);
    lessonIds.add(lesson.lessonId);
    lessonCodes.add(lesson.lessonCode);
    assert(lesson.fill.length === 3, `${lesson.lessonCode}填空题字段不完整`);
    assert(lesson.single.length === 4 && lesson.single[1].length === 4, `${lesson.lessonCode}单选题字段不完整`);
    assert(lesson.multiple.length === 4 && lesson.multiple[1].length === 4, `${lesson.lessonCode}多选题字段不完整`);
    assert(lesson.trueFalse.length === 3, `${lesson.lessonCode}判断题字段不完整`);
    assert(/^[A-D]$/.test(lesson.single[2]), `${lesson.lessonCode}单选答案无效`);
    assert(lesson.multiple[2].length >= 2 && new Set(lesson.multiple[2]).size === lesson.multiple[2].length, `${lesson.lessonCode}多选答案无效`);
    assert(["A", "B"].includes(lesson.trueFalse[1]), `${lesson.lessonCode}判断答案无效`);
  }
}

function questionRows(bank) {
  const rows = [];
  const answerKeys = ["A", "B", "C", "D"];
  for (const [lessonIndex, lesson] of bank.lessons.entries()) {
    const optionShift = lessonIndex % answerKeys.length;
    const rotateOptions = (options) => [...options.slice(optionShift), ...options.slice(0, optionShift)];
    const rotateAnswer = (answer) => {
      const originalIndex = answerKeys.indexOf(answer);
      return answerKeys[(originalIndex - optionShift + answerKeys.length) % answerKeys.length];
    };
    const [fillStem, fillAnswer, fillExplanation] = lesson.fill;
    rows.push([lesson.lessonId, lesson.lessonCode, TYPE_ORDER[0], fillStem, "", "", "", "", fillAnswer, fillExplanation]);

    const [singleStem, singleOptions, singleAnswer, singleExplanation] = lesson.single;
    rows.push([lesson.lessonId, lesson.lessonCode, TYPE_ORDER[1], singleStem, ...rotateOptions(singleOptions), rotateAnswer(singleAnswer), singleExplanation]);

    const [multipleStem, multipleOptions, multipleAnswers, multipleExplanation] = lesson.multiple;
    const rotatedMultipleAnswers = multipleAnswers.map(rotateAnswer).sort();
    rows.push([lesson.lessonId, lesson.lessonCode, TYPE_ORDER[2], multipleStem, ...rotateOptions(multipleOptions), rotatedMultipleAnswers.join(","), multipleExplanation]);

    const [trueFalseStem, trueFalseAnswer, trueFalseExplanation] = lesson.trueFalse;
    rows.push([lesson.lessonId, lesson.lessonCode, TYPE_ORDER[3], trueFalseStem, "正确", "错误", "", "", trueFalseAnswer, trueFalseExplanation]);
  }
  assert(rows.length === 196, `题目必须为196行，当前为${rows.length}行`);
  const slots = new Set(rows.map((row) => `${row[0]}:${row[2]}`));
  assert(slots.size === 196, "存在重复的课时题型槽位");
  for (const [index, row] of rows.entries()) {
    assert(row[3] && row[8] && row[9], `第${index + 2}行的题干、答案或解析为空`);
    for (const value of row) {
      if (typeof value === "string") assert(!/^[=+\-@]/.test(value.trimStart()), `第${index + 2}行包含危险单元格前缀`);
    }
  }
  return rows;
}

const bank = JSON.parse(await fs.readFile(sourcePath, "utf8"));
validateBank(bank);
const rows = questionRows(bank);

const workbook = Workbook.create();
const questions = workbook.worksheets.add("题目导入");
const guide = workbook.worksheets.add("填写说明");
questions.showGridLines = false;
guide.showGridLines = false;

questions.getRange(`A1:J${rows.length + 1}`).values = [HEADERS, ...rows];
questions.getRange("A1:J197").format.font = { name: "Arial", size: 10, color: "#1F2937" };
questions.getRange("A1:J1").format = {
  fill: "#4267D5",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "inside", style: "thin", color: "#FFFFFF" },
};
questions.getRange("A2:C197").format.fill = "#E9EEF8";
questions.getRange("D2:J197").format.fill = "#FFF9E6";
questions.getRange("A2:J197").format.verticalAlignment = "top";
questions.getRange("A2:J197").format.wrapText = true;
questions.getRange("A1:J197").format.borders = {
  insideHorizontal: { style: "thin", color: "#E5E7EB" },
  bottom: { style: "thin", color: "#CBD5E1" },
};
questions.getRange("A1:A197").format.columnWidth = 25;
questions.getRange("B1:B197").format.columnWidth = 12;
questions.getRange("C1:C197").format.columnWidth = 10;
questions.getRange("D1:D197").format.columnWidth = 42;
questions.getRange("E1:H197").format.columnWidth = 24;
questions.getRange("I1:I197").format.columnWidth = 18;
questions.getRange("J1:J197").format.columnWidth = 42;
questions.getRange("A1:J1").format.rowHeight = 24;
questions.freezePanes.freezeRows(1);
questions.getRange("C2:C197").dataValidation = { rule: { type: "list", values: TYPE_ORDER } };
questions.tables.add("A1:J197", true, "QuestionImportTable").style = "TableStyleMedium2";

const guideRows = [
  ["题库批量导入说明", ""],
  ["内容版本", bank.version],
  ["课程", `${bank.title}（${bank.courseId}）`],
  ["题目规模", "49个课时，每课时填空、单选、多选、判断各1题，共196题"],
  ["当前状态", "待独立审核；导入后由具备审核权限且非出题人的账号逐题审核"],
  ["导入约束", "不得增删行或修改课时标识、课时编号和题型；题干、答案、解析均不能为空"],
  ["答案格式", "单选填一个字母；多选用英文逗号分隔；判断填A或B；填空多个答案用竖线分隔"],
  ["安全约束", "任何公式或以等号、加号、减号、@开头的文本都会被系统拒绝"],
  ["权威来源", ""],
  ...bank.sources.map((source, index) => [`来源${index + 1}`, `${source.title} ${source.url}`]),
];
guide.getRange(`A1:B${guideRows.length}`).values = guideRows;
guide.getRange(`A1:B${guideRows.length}`).format.font = { name: "Arial", size: 10, color: "#1F2937" };
guide.getRange("A1:B1").format = {
  fill: "#1F3A8A",
  font: { name: "Arial", size: 14, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
};
guide.getRange("A2:A8").format = { fill: "#E9EEF8", font: { name: "Arial", size: 10, bold: true, color: "#1F2937" } };
guide.getRange(`A9:B9`).format = { fill: "#DCE6F1", font: { name: "Arial", size: 10, bold: true, color: "#1F2937" } };
guide.getRange(`A10:A${guideRows.length}`).format.font = { name: "Arial", size: 10, bold: true, color: "#1F2937" };
guide.getRange(`A1:B${guideRows.length}`).format.wrapText = true;
guide.getRange(`A1:B${guideRows.length}`).format.verticalAlignment = "top";
guide.getRange(`A1:B${guideRows.length}`).format.borders = {
  insideHorizontal: { style: "thin", color: "#E5E7EB" },
  bottom: { style: "thin", color: "#CBD5E1" },
};
guide.getRange(`A1:A${guideRows.length}`).format.columnWidth = 22;
guide.getRange(`B1:B${guideRows.length}`).format.columnWidth = 105;
guide.getRange("A1:B1").format.rowHeight = 28;

workbook.recalculate();

const questionCheck = await workbook.inspect({
  kind: "table",
  range: "题目导入!A1:J8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 10,
});
const tailCheck = await workbook.inspect({
  kind: "table",
  range: "题目导入!A190:J197",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 10,
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});

await fs.mkdir(outputDir, { recursive: true });
const topPreview = await workbook.render({ sheetName: "题目导入", range: "A1:J12", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "question-bank-preview-top.png"), new Uint8Array(await topPreview.arrayBuffer()));
const tailPreview = await workbook.render({ sheetName: "题目导入", range: "A188:J197", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "question-bank-preview-tail.png"), new Uint8Array(await tailPreview.arrayBuffer()));
const guidePreview = await workbook.render({ sheetName: "填写说明", range: `A1:B${guideRows.length}`, scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "question-bank-preview-guide.png"), new Uint8Array(await guidePreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({
  outputPath,
  lessons: bank.lessons.length,
  questions: rows.length,
  questionCheck: questionCheck.ndjson,
  tailCheck: tailCheck.ndjson,
  formulaErrors: formulaErrors.ndjson,
}, null, 2));
