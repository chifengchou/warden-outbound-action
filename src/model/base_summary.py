from typing import List, Optional

from horangi.signals.message import ContentModel
from pydantic import BaseModel, Field


class Entity(BaseModel):
    """
    Entity represents either a resource or a service. If it's a service entity,
    then `gid` is None.
    """

    is_service: bool = Field(description="The entity represents a service")
    region: str
    service: str
    severity: str
    # gid is None if is_service
    gid: Optional[str] = Field(
        None, description="Entity gid. Null if is_service"
    )  # noqa
    note: Optional[str]


class Rule(BaseModel):
    """
    Rule and its target resources
    """

    rule: str
    default_severity: str
    resources: List[Entity] = Field(default_factory=list)
    tags: Optional[List[str]] = Field(
        default_factory=list, description="Compliance tags"
    )
