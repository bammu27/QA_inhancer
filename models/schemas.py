from typing import Optional, Union, Literal
from pydantic import BaseModel, field_validator


class FieldObject(BaseModel):
    value: Optional[Union[str, list[str]]] = None
    source: Literal["tester_provided", "ai_annotated", "missing"]

    @field_validator("value", mode="before")
    def format_value(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            cleaned = [str(item).strip() for item in v if str(item).strip()]
            return "\n".join(cleaned) if cleaned else None
        if isinstance(v, str):
            v_str = v.strip()
            return v_str if v_str else None
        return str(v)


class DeveloperNotes(BaseModel):
    description: str
    common_fixes: list[str]


class ReportObject(BaseModel):
    category: str
    fields: dict[str, FieldObject]
    developer_notes: Optional[DeveloperNotes] = None
