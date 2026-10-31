"""Strict inputs for reviewed voucher forms, separate from general document export."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSelection(StrictModel):
    note_id: UUID
    voucher_session_no: int = Field(ge=1, le=8)
    actual_service_date: date
    delivered_attested: Literal[True]

    @model_validator(mode="after")
    def check_delivered_date(self):
        if self.actual_service_date > datetime.now(timezone(timedelta(hours=9))).date():
            raise ValueError("실제 제공한 서비스의 날짜를 확인해주세요.")
        return self


class RecordRow(SourceSelection):
    content_left: str = Field(max_length=2000)
    content_right: str = Field(default="", max_length=2000)


class VoucherForm(StrictModel):
    template: Literal["form10", "form25", "form26"]
    report_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    service_tier: Literal["", "type_1", "type_2"] = ""
    rows: list[RecordRow] = Field(default_factory=list, max_length=8)
    general_comment: str = Field(default="", max_length=2000)
    # Empty test results and administrative fields remain empty, never inferred.
    purpose: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=2000)
    schedule: str = Field(default="", max_length=2000)
    price: str = Field(default="", max_length=1000)
    contract_period: str = Field(default="", max_length=1000)
    plan_left: str = Field(default="", max_length=3000)
    plan_right: str = Field(default="", max_length=3000)
    additional_cost: str = Field(default="", max_length=1000)
    refund_terms: str = Field(default="", max_length=2000)
    other_terms: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def check_record(self):
        contract_only = ('additional_cost', 'refund_terms', 'other_terms')
        if self.template != 'form25' and any(getattr(self, key) for key in contract_only):
            raise ValueError("현재 서식에서 출력할 수 없는 항목이 있습니다.")
        if self.template == "form10":
            if any(getattr(self, key) for key in ('purpose', 'content', 'schedule', 'price', 'contract_period', 'plan_left', 'plan_right')):
                raise ValueError("현재 서식에서 출력할 수 없는 항목이 있습니다.")
            if not self.rows:
                raise ValueError("기록할 회기를 선택해주세요.")
            numbers = [row.voucher_session_no for row in self.rows]
            notes = [row.note_id for row in self.rows]
            if len(set(numbers)) != len(numbers) or len(set(notes)) != len(notes):
                raise ValueError("회기 또는 바우처 회차가 중복되었습니다.")
            for row in self.rows:
                if row.actual_service_date.strftime("%Y-%m") != self.report_month:
                    raise ValueError("같은 달의 회기만 선택해주세요.")
                if not row.content_left.strip():
                    raise ValueError("각 회기의 서비스 내용을 작성해주세요.")
        elif self.template == 'form25':
            if self.rows or any(getattr(self, key) for key in ('general_comment', 'service_tier', 'purpose', 'plan_left', 'plan_right')):
                raise ValueError("현재 서식에서 출력할 수 없는 항목이 있습니다.")
            if any(not getattr(self, key).strip() for key in ('contract_period', 'content', 'schedule', 'price', 'additional_cost', 'refund_terms')):
                raise ValueError("계약기간·내용·시간·횟수·금액·추가비용·환불규정을 작성해주세요.")
        elif self.rows or self.general_comment or self.service_tier or not self.purpose.strip() or not self.content.strip() or not self.plan_left.strip():
            raise ValueError("계획서의 목적·내용·제공계획을 작성해주세요.")
        return self


class MapRequest(StrictModel):
    case_id: str = Field(min_length=1, max_length=100)
    sources: list[SourceSelection] = Field(min_length=1, max_length=8)


class PrepareRequest(StrictModel):
    case_id: str = Field(min_length=1, max_length=100)
    operation_key: UUID
    form: VoucherForm
    source_hashes: dict[str, str] = Field(default_factory=dict, max_length=8)


class ReviewRequest(StrictModel):
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_privacy_reviewed: Literal[True]
    acknowledged_offline_completion: Literal[True]


class ExportRequest(StrictModel):
    format: Literal["pdf", "hwpx"]
