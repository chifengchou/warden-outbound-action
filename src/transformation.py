import json
import logging
import os
from typing import Dict, List, Optional

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    batch_processor,
)
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext
from blinker import signal
from horangi import IS_AWS
from horangi.constants import (
    ActionType,
    CheckHistoryEvent,
    CheckResult,
    DestinationType,
)
from horangi.generated.severity_level import SeverityLevel
from horangi.models import (
    Action,
    CheckHistory,
    FindingsDefinition,
    ScanFindingsDefinitionMapping,
)
from horangi.models.core import session
from horangi.querybakery.baked_queries import (
    query_check_history_contexts,
    query_filtered_checks,
)
from horangi.signals.message import Message
from horangi.signals.message_storyfier import IndexCompleteV1
from horangi.signals.message_util import register

from constant import LOG_LEVEL, OUTBOUND_EVENT_BUS_NAME, SQL_ECHO
from model.sns_summary import Resource, Rule, SnsSummaryInputV1, SnsSummaryV1
from util.middleware import middleware_db_connect
from util.query import query_enabled_destinations

POWERTOOLS_METRICS_NAMESPACE = os.environ.get(
    "POWERTOOLS_METRICS_NAMESPACE", "outbound"
)
POWERTOOLS_SERVICE_NAME = os.environ.get("POWERTOOLS_SERVICE_NAME")

if not POWERTOOLS_SERVICE_NAME:
    if IS_AWS:
        raise AssertionError("Env var POWERTOOLS_SERVICE_NAME is not set.")
    else:
        POWERTOOLS_SERVICE_NAME = "transformation"


logger = Logger(level=logging.getLevelName(LOG_LEVEL))
logger.info(
    f"{POWERTOOLS_METRICS_NAMESPACE=}, {POWERTOOLS_SERVICE_NAME=}, {IS_AWS=}, "
    f"{LOG_LEVEL=}, {SQL_ECHO=}"
)

# NOTE: To disable tracing set ENV:
#   POWERTOOLS_TRACE_DISABLED="1"
#   POWERTOOLS_TRACE_MIDDLEWARES="False"
tracer = Tracer()
metrics = Metrics()

# Infra must enable "Report Batch Item Failures"
processor = BatchProcessor(event_type=EventType.SQS)


@tracer.capture_method(capture_response=False)
def get_aggregated_by_rules(
    org_uid,
    task_uid,
    filters,
) -> List[Rule]:
    if filters and filters.get("severities"):
        severities = filters.get('severities')
    else:
        severities = None

    sess = session()
    # The check_history records created by the given task
    # (action_uid, findings_definition_name, context_id)
    signatures_subq = query_check_history_contexts(
        sess, task_uid, subquery=True
    )  # noqa
    # only new failed related records
    signatures_subq.add_criteria(
        lambda q: q.filter(
            CheckHistory.event_type.in_(
                [
                    CheckHistoryEvent.first_seen.value,
                    CheckHistoryEvent.reappeared.value,
                    CheckHistoryEvent.pass_to_fail.value,
                ]
            ),
            CheckHistory.result == CheckResult.fail.value,
        )
    )
    signatures_subq = (
        signatures_subq.to_query(sess).params(task_uid=task_uid).subquery()
    )
    checks_subq = query_filtered_checks(
        sess,
        org_uid,
        subquery=True,
        task_uids=[task_uid],
        severities=severities,
        results=[CheckResult.fail.value],
    )
    checks_subq = (
        checks_subq.to_query(sess)
        .params(
            task_uids=[task_uid],
            severities=severities,
            results=[CheckResult.fail.value],
        )
        .subquery()
    )
    rows = sess.query(
        *checks_subq.c,
        FindingsDefinition.title,
        FindingsDefinition.tags,
    ).filter(
        checks_subq.c.findings_definition_uid == FindingsDefinition.uid,
        # The sub-queries are already filtered by task_uid. Filter by
        # context_id is enough
        checks_subq.c.context_id == signatures_subq.c.context_id,
        checks_subq.c.findings_definition_uid == FindingsDefinition.uid,
        # Make sure check's FindingsDefinition has
        # signature.c.findings_definition_name
        ScanFindingsDefinitionMapping.findings_definition_name
        == signatures_subq.c.findings_definition_name,
        ScanFindingsDefinitionMapping.findings_definition_uid
        == FindingsDefinition.uid,  # noqa
    )
    # NOTE: Within a single scan(task), a resource should only appear at most
    #  once for a rule.
    rules: Dict[str, Rule] = dict()
    for row in rows:
        try:
            if row.resource_gid:
                resource = Resource(
                    is_service=False,
                    region=row.resource_region,
                    service=row._params.get('service'),
                    severity=SeverityLevel(row.severity).name,
                    gid=row.resource_gid,
                    note=row.note,
                )
            else:
                resource = Resource(
                    is_service=True,
                    region=row._params.get('region'),
                    service=row._params.get('service'),
                    severity=SeverityLevel(row.severity).name,
                    note=row.note,
                )

            # Only compliance tags
            tags = list(filter(lambda t: t.startswith("compliance:"), row.tags))  # noqa
            aggregated = rules.get(row.title)
            if aggregated is None:
                aggregated = Rule(
                    rule=row.title,
                    default_severity=row.default_severity,
                    resources=[resource],
                    tags=tags,
                )
                rules[row.title] = aggregated
            else:
                aggregated.resources.append(resource)
        except Exception:
            logger.exception("Fail to fetch a row")
            # ignored

    return list(rules.values())


@tracer.capture_method(capture_response=False)
def create_summary_for_sns(m: Message[IndexCompleteV1], **_) -> None:
    task_uid = m.content.task_uid
    logger.debug(f"create_summary_for_sns for {task_uid=}")
    action: Action = session.query(Action).get(m.content.action_uid)
    if action.action_type != ActionType.cloud_scan.value:
        logger.info(f"Only {ActionType.cloud_scan} is supported")
        return

    entries = []
    # NOTE: For now all destinations share the same "filters". Therefore, we
    #  only query aggregated once.
    aggregated: Optional[List[Rule]] = None
    for config, destination in query_enabled_destinations(
        action.action_group, DestinationType.aws_sns
    ):  # noqa
        try:
            logger.debug(f"Process {destination.uid=}")
            if aggregated is None:
                aggregated = get_aggregated_by_rules(
                    action.org_uid, task_uid, config.filters
                )
            content = SnsSummaryInputV1(
                sns_topic_arn=destination.sns_topic_arn,
                summary=SnsSummaryV1(
                    cloud_provider=action.cloud_provider_type,
                    scan_group=action.action_group.name,
                    target_name=action.target_name,
                    rules=aggregated,
                ),
            )
            msg = Message[SnsSummaryInputV1](
                msg_type="SnsSummaryInput",
                version="1",
                content=content,
                # Route to sender
                msg_attrs={"route": "ready_to_send"},
            )
            logger.debug(msg)
            entries.append(
                {
                    'EventBusName': OUTBOUND_EVENT_BUS_NAME,
                    'Source': POWERTOOLS_SERVICE_NAME,
                    'DetailType': "OutboundNotification",
                    'Detail': msg.json(),
                }
            )
        except Exception:
            logger.exception(
                f"Failed to create summary for {destination.uid}. Continue"
            )
            # ignore

    logger.info(f"Send {len(entries)} events")
    if entries:
        client = boto3.client("events")
        resp = client.put_events(Entries=entries)
        logger.info(resp)


register(msg_cls=Message[IndexCompleteV1], receiver=create_summary_for_sns)


@tracer.capture_method(capture_response=False)
def record_handler(record: SQSRecord):
    # TODO: handler should be in a nested db transaction
    logger.info(record.raw_event)
    obj = json.loads(record.body)
    detail = obj["detail"]
    msg_type_id = Message.parse_msg_type_id(detail)
    s = signal(msg_type_id)
    if s.receivers:
        s.send(detail)
    else:
        logger.info(f"No receiver for {msg_type_id=}")


@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler(capture_response=False)
@middleware_db_connect  # should come before batch_processor
@batch_processor(record_handler=record_handler, processor=processor)
def handler(event, context: LambdaContext):
    return processor.response()
