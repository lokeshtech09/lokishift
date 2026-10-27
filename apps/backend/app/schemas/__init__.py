"""Request/response schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ai_limits import MAX_JOB_CHARACTERS

# -- settings / health ---------------------------------------------------------

ProviderLiteral = Literal[
    "openai",
    "anthropic",
    "gemini",
    "openrouter",
    "deepseek",
    "groq",
    "azure_foundry",
    "ollama",
    "openai_compatible",
]
EffortLiteral = Literal["minimal", "low", "medium", "high"]


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    provider: ProviderLiteral
    model: str = Field(min_length=1, max_length=120)
    # Write-only: stored encrypted, never returned.
    api_key: str | None = Field(default=None, max_length=500)
    api_base: str | None = Field(default=None, max_length=300)
    reasoning_effort: EffortLiteral | None = None
    use_as_backup: bool = True
    make_default: bool = False


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    provider: ProviderLiteral | None = None
    model: str | None = Field(default=None, min_length=1, max_length=120)
    # Write-only. Omit to keep the saved key; "" removes it.
    api_key: str | None = Field(default=None, max_length=500)
    api_base: str | None = Field(default=None, max_length=300)
    reasoning_effort: EffortLiteral | Literal[""] | None = None
    use_as_backup: bool | None = None


class ReorderRequest(BaseModel):
    connection_ids: list[str] = Field(min_length=1, max_length=50)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


class StatusResponse(BaseModel):
    """Application status response."""

    status: str
    llm_configured: bool
    llm_healthy: bool
    has_resumes: bool


# -- profiles --------------------------------------------------------------------


class ExperienceItem(BaseModel):
    title: str = Field(default="", max_length=120)
    company: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=120)
    work_mode: str = Field(default="", max_length=20)
    domain: str = Field(default="", max_length=60)
    start: str = Field(default="", max_length=20)
    end: str = Field(default="", max_length=20)


class ProfileFields(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    full_name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=160)
    phone: str = Field(default="", max_length=40)
    linkedin: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=120)
    total_experience: str = Field(default="", max_length=40)
    summary: str = Field(default="", max_length=4000)
    experience: list[ExperienceItem] = Field(default_factory=list, max_length=30)


class ProfileUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    full_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    linkedin: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=120)
    total_experience: str | None = Field(default=None, max_length=40)
    summary: str | None = Field(default=None, max_length=4000)
    experience: list[ExperienceItem] | None = Field(default=None, max_length=30)


class RenameResumeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


# -- tasks -----------------------------------------------------------------------


class TaskCreate(BaseModel):
    profile_id: str
    job_title: str = Field(min_length=1, max_length=160)
    job_location: str = Field(min_length=1, max_length=160)
    vendor_company: str = Field(min_length=1, max_length=160)
    domain: str = Field(default="", max_length=60)
    job_description: str = Field(min_length=50, max_length=MAX_JOB_CHARACTERS)
    recruiter_name: str = Field(default="", max_length=120)
    recruiter_email: str = Field(default="", max_length=160)
    vendor_name: str = Field(default="", max_length=120)
    vendor_email: str = Field(default="", max_length=160)
    ai_instructions: str = Field(default="", max_length=2000)
    # Start tailoring as soon as matching finishes.
    auto_tailor: bool = False
    # Run this task on a specific AI connection (None = the default).
    connection_id: str | None = None


class TailorRequest(BaseModel):
    # Tailor a resume other than the recommended one.
    resume_id: str | None = None
    ai_instructions: str | None = Field(default=None, max_length=2000)

