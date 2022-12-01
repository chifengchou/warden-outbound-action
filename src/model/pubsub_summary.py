from typing import Dict, List

from horangi.signals.message import ContentModel

from .base_summary import Rule


class PubSubSummaryV1(ContentModel, msg_type_id=("PubSubSummary", "1")):
    """
    Model of data sent to PubSub topic by PubSub topic sender
    """

    cloud_provider: str
    scan_group: str
    target_name: str
    rules: List[Rule]


class PubSubSummaryInputV1(ContentModel, msg_type_id=("PubSubSummaryInput", "1")):
    """
    Model of data prepared for PubSub topic sender
    """

    org_uid: str
    task_uid: str
    topic_id: str
    project_id: str
    encrypted_credentials: Dict
    summary: PubSubSummaryV1
