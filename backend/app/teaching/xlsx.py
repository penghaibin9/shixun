from io import BytesIO
from itertools import islice

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from app.common.xlsx import XlsxValidationError, validate_xlsx_archive


HEADERS = ["学号*", "姓名*", "班级", "手机号（可选）", "邮箱（可选）"]
MAX_MEMBER_IMPORT_ROWS = 1000


def template_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "学生导入"
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4267D5")
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 22
    sheet.column_dimensions["D"].width = 18
    sheet.column_dimensions["E"].width = 28
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def parse_members(data: bytes, expected_class_name: str | None = None) -> tuple[list[dict], list[dict]]:
    try:
        validate_xlsx_archive(data)
    except XlsxValidationError as exc:
        raise ValueError(str(exc)) from exc
    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=False)
    except Exception as exc:
        raise ValueError("文件不是有效的 XLSX") from exc
    try:
        sheet = workbook.active
        header = next(sheet.iter_rows(min_row=1, max_row=1, min_col=1, max_col=5, values_only=True), None)
        if not header or list(header) != HEADERS:
            raise ValueError("模板表头不匹配")
        rows = list(islice(sheet.iter_rows(min_row=2, min_col=1, max_col=5, values_only=True), MAX_MEMBER_IMPORT_ROWS + 1))
        if len(rows) > MAX_MEMBER_IMPORT_ROWS:
            raise ValueError(f"单次最多导入 {MAX_MEMBER_IMPORT_ROWS} 行学生")
        valid, errors, seen = [], [], set()
        for row_number, row in enumerate(rows, start=2):
            values = list(row[:5]) + [None] * max(0, 5 - len(row))
            if all(value in (None, "") for value in values):
                errors.append({"row_number": row_number, "student_number": "", "student_name": "", "class_name": "", "phone": "", "email": "", "reason": "空白行"})
                continue
            number, name, class_name, phone, email = values[:5]
            reasons = []
            for value in values:
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    reasons.append("包含公式或危险前缀")
                    break
            number, name = str(number or "").strip(), str(name or "").strip()
            normalized_class_name = str(class_name or "").strip()
            if not number:
                reasons.append("学号不能为空")
            if not name:
                reasons.append("姓名不能为空")
            if normalized_class_name and expected_class_name and normalized_class_name != expected_class_name.strip():
                reasons.append("班级与当前导入目标不一致")
            if number in seen:
                reasons.append("批次内学号重复")
            seen.add(number)
            if len(number) > 64 or len(name) > 80 or len(str(phone or "")) > 32 or len(str(email or "")) > 160:
                reasons.append("字段长度超过限制")
            item = {"row_number": row_number, "student_number": number, "student_name": name, "class_name": normalized_class_name, "phone": str(phone or ""), "email": str(email or "")}
            if reasons:
                errors.append({**item, "reason": "；".join(reasons)})
            else:
                valid.append(item)
        return valid, errors
    finally:
        workbook.close()


def error_rows_bytes(errors: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "错误行"
    sheet.append(["原行号", *HEADERS, "错误原因"])
    for item in errors:
        sheet.append([item["row_number"], item["student_number"], item["student_name"], item["class_name"], item["phone"], item["email"], item["reason"]])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
