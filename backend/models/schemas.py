"""Pydantic models for API request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    """Request body for creating a new project."""
    name: str
    client: str
    subsidiaries: str = ""
    contacts: str = ""
    notes: str = ""


class ProjectEntitiesUpdate(BaseModel):
    """Request body for updating project entities."""
    entities: dict[str, list[str]]


class SeedEntitiesRequest(BaseModel):
    """Request body for seeding entities from manual user inputs."""
    name: str
    client: str
    subsidiaries: str = ""
    contacts: str = ""
    notes: str = ""


class AnonymizeRequest(BaseModel):
    """Request body for anonymization (sent alongside file upload)."""
    project_id: str | None = None
    confirmed_ai: list[dict] = []
    # Manual entities when no project is selected
    manual_entities: dict[str, list[str]] | None = None


class DeanonymizeRequest(BaseModel):
    """Mapping data for de-anonymization (sent alongside file upload)."""
    mapping: dict


class Highlight(BaseModel):
    """A single highlighted entity in the preview."""
    start: int
    end: int
    entity: str
    source_entity: str = ""
    placeholder: str
    status: str  # "confirmed", "uncertain"
    score: int | None = None


class TextBlockPreview(BaseModel):
    """A text block with highlights for the preview."""
    text: str
    highlights: list[Highlight]


class SectionPreview(BaseModel):
    """A section (slide/page) in the preview."""
    label: str
    text_blocks: list[TextBlockPreview]


class PreviewSummary(BaseModel):
    """Summary counts for the preview."""
    confirmed: int
    uncertain: int


class PreviewResponse(BaseModel):
    """Full preview response."""
    sections: list[SectionPreview]
    summary: PreviewSummary
