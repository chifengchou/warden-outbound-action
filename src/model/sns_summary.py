from typing import List

from horangi.signals.message import ContentModel

from .base_summary import Rule


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

    org_uid: str
    task_uid: str
    sns_topic_arn: str
    summary: SnsSummaryV1
