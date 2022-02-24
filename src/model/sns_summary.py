from typing import List, Optional

from horangi.signals.message import ContentModel
from pydantic import BaseModel, Field


class Resource(BaseModel):
    """
    Resource represents both resources and services. The latter is
    """

    is_service: bool
    region: str
    service: str
    severity: str
    # gid is None if is_service
    gid: Optional[str] = Field(description="Resource gid")
    note: Optional[str]


class AggregatedByRule(BaseModel):
    rule: str
    default_severity: str
    resources: List[Resource] = Field(default_factory=list)
    tags: Optional[List[str]] = Field(
        default_factory=list, description="compliance tags"
    )


class SnsSummaryV1(ContentModel, msg_type_id=("SnsSummary", "1")):
    """
    Model of Message[SnsSummaryV1].content
    """

    sns_topic_arn: str
    cloud_provider: str
    action_group_name: str
    target_name: str
    rules: List[AggregatedByRule]
