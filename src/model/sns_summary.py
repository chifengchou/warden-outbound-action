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


class SnsSummaryV1(ContentModel, msg_type_id=("SnsSummary", "1")):
    """
    Model of data sent to SNS topic by SNS topic sender
    """

    cloud_provider: str
    scan_group: str
    target_name: str
    rules: List[Rule]


class SnsSummaryInputV1(ContentModel, msg_type_id=("SnsSummaryInput", "1")):
    """
    Model of data prepared for SNS topic sender
    """

    sns_topic_arn: str
    summary: SnsSummaryV1
