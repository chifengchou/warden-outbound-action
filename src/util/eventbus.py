from datetime import datetime
from typing import List

import boto3
from horangi.signals.message import ContentModel, Message

from constant import OUTBOUND_EVENT_BUS_NAME


def put_events(
    messages: List[Message[ContentModel]],
    *,
    source: str,
    detail_type: str = "OutboundNotification",
    trace_header: str = None
):
    entries = []
    current = datetime.utcnow()
    for msg in messages:
        entry = {
            'Time': current,
            'EventBusName': OUTBOUND_EVENT_BUS_NAME,
            'Source': source,
            'DetailType': detail_type,
            'Detail': msg.json(),
        }
        if trace_header:
            entry.update(
                {
                    'TraceHeader': trace_header,
                }
            )

        entries.append(entry)

    client = boto3.client("events")
    return client.put_events(Entries=entries)
