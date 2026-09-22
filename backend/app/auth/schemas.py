from typing import Literal

from pydantic import BaseModel, Field, model_validator


AccountRole = Literal["admin", "teacher", "student"]
AccountStatus = Literal["ACTIVE", "DISABLED"]


class AccountCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    role: AccountRole
    status: AccountStatus = "ACTIVE"
    external_subject: str | None = Field(default=None, min_length=1, max_length=191)
    login_name: str | None = Field(default=None, min_length=1, max_length=128)
    teacher_id: str | None = Field(default=None, min_length=1, max_length=36)
    staff_number: str | None = Field(default=None, min_length=1, max_length=64)
    student_id: str | None = Field(default=None, min_length=1, max_length=36)
    student_number: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def profile_matches_role(self):
        if not (self.external_subject or self.login_name):
            raise ValueError("账号必须提供外部主体标识或登录名")
        if self.role == "student" and not self.student_number:
            raise ValueError("学生账号必须提供学号")
        if self.role != "student" and (self.student_id or self.student_number or self.phone or self.email):
            raise ValueError("仅学生账号可以提供学生档案字段")
        if self.role == "teacher" and self.student_id:
            raise ValueError("教师账号不能关联学生档案")
        if self.role != "teacher" and (self.teacher_id or self.staff_number):
            raise ValueError("仅教师账号可以提供教师档案字段")
        return self


class AccountView(BaseModel):
    user_id: str
    display_name: str
    role: AccountRole
    status: AccountStatus
    external_subject: str | None
    login_name: str | None
    teacher_id: str | None = None
    staff_number: str | None = None
    student_id: str | None = None
    student_number: str | None = None
    phone: str | None = None
    email: str | None = None


class AccountListResponse(BaseModel):
    items: list[AccountView]
    page: int
    page_size: int
    total: int


class IdentityReconciliationScanResponse(BaseModel):
    """历史名单身份核对扫描结果；不会改写 class_membership。"""

    examined_count: int
    valid_count: int
    created_case_count: int
    existing_case_count: int
