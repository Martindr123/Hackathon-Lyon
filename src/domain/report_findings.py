from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.report_determinist import ReportDeterminist
from src.domain.report_agent import ReportAgent


class ReportFindings(BaseModel):
    """REPORT section — split into deterministic (computed) and agent (LLM-generated) parts."""

    report_determinist: ReportDeterminist = Field(default_factory=ReportDeterminist)
    report_agent: ReportAgent = Field(default_factory=ReportAgent)
