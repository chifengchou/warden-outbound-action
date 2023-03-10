import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Union

import boto3
import sentry_sdk
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    batch_processor,
)
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext
from blinker import signal
from horangi import ENVIRONMENT_MODE, IS_AWS
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
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

from constant import LOG_LEVEL, OUTBOUND_EVENT_BUS_NAME, SQL_ECHO
from model import (
    Entity,
    PubSubSummaryInputV1,
    PubSubSummaryV1,
    Rule,
    SnsSummaryInputV1,
    SnsSummaryV1,
)
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

sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        sentry_dsn,
        integrations=[AwsLambdaIntegration(timeout_warning=True)],
        environment=ENVIRONMENT_MODE,
    )

MAX_RECEIVE_COUNT = int(os.environ.get("MAX_RECEIVE_COUNT", "3"))

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
def query_rules(
    org_uid: str,
    task_uid: str,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Rule]:
    """
    Query `first_seen`, `reappeared` and `pass_to_fail` checks from the given
    task. Aggregate them to be a list of Rules.
    Args:
        org_uid (str):
        task_uid (str):
        filters (Optional[Dict[str, Any]]): a dictionary of filters. ATM, only
            'severities'(List[int]) is supported

    Returns:
        A list of Rule

    """
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
                resource = Entity(
                    is_service=False,
                    region=row.resource_region,
                    service=row._params.get('service'),
                    severity=SeverityLevel(row.severity).name,
                    gid=row.resource_gid,
                    note=row.note,
                )
            else:
                resource = Entity(
                    is_service=True,
                    region=row._params.get('region'),
                    service=row._params.get('service'),
                    severity=SeverityLevel(row.severity).name,
                    note=row.note,
                )

            # Only compliance tags
            tags = list(
                filter(lambda t: t.startswith("compliance:"), row.tags)
            )  # noqa
            aggregated = rules.get(row.title)
            if aggregated is None:
                aggregated = Rule(
                    rule=row.title,
                    default_severity=SeverityLevel(row.default_severity).name,
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


def transform_message(
    message: Message[IndexCompleteV1],
) -> Iterable[Message[Union[SnsSummaryInputV1, PubSubSummaryInputV1]]]:
    """
    Transform the incoming `Message[IndexCompleteV1]` to one or more
    `Message[SnsSummaryInputV1]` or `Message[PubSubSummaryInputV1]`
    Args:
        message (Message[IndexCompleteV1]):

    Returns:
        A generator of Message[SnsSummaryInputV1]
    """
    task_uid = message.content.task_uid
    logger.debug(f"create_summary_for_sns for {task_uid=}")
    action: Action = session.query(Action).get(message.content.action_uid)
    if action.action_type != ActionType.cloud_scan.value:
        logger.info(f"Only {ActionType.cloud_scan} is supported")
        return

    # NOTE: For now all destinations share the same "filters". Therefore, we
    #  only query aggregated once.
    aggregated: Optional[List[Rule]] = None
    for config, destination in query_enabled_destinations(
        action.action_group, [DestinationType.aws_sns, DestinationType.pubsub]
    ):  # noqa
        try:
            logger.debug(f"Process {destination.uid=}")
            if aggregated is None:
                aggregated = query_rules(action.org_uid, task_uid, config.filters)
            if destination.destination_type == DestinationType.aws_sns.value:
                # data_model = SnsSummaryV1
                content = SnsSummaryInputV1(
                    org_uid=message.content.org_uid,
                    task_uid=task_uid,
                    sns_topic_arn=destination.sns_topic_arn,
                    summary=SnsSummaryV1(
                        cloud_provider=action.cloud_provider_type,
                        scan_group=action.action_group.name,
                        target_name=action.target_name,
                        rules=aggregated,
                    ),
                )
            elif destination.destination_type == DestinationType.pubsub.value:
                content = PubSubSummaryInputV1(
                    org_uid=message.content.org_uid,
                    task_uid=task_uid,
                    topic_id=destination.topic_id,
                    project_id=destination.project_id,
                    encrypted_credentials=destination.meta["credentials"],
                    summary=PubSubSummaryV1(
                        cloud_provider=action.cloud_provider_type,
                        scan_group=action.action_group.name,
                        target_name=action.target_name,
                        rules=aggregated,
                    ),
                )
            else:
                raise ValueError(
                    f"Unsupported destination_type {destination.destination_type}"
                )
            # allow Nonetype error to raise
            message_type, version = content.get_msg_type_id()  # type: ignore

            msg = Message[content.__class__](
                msg_type=message_type,
                version=version,
                content=content,
                # Will be routed to sender by the event bus
                msg_attrs={"route": "ready_to_send"},
            )
            yield msg
        except Exception:  # noqa
            logger.exception(
                f"Failed to create summary for {destination.uid}. Continue"
            )
            # ignore


@tracer.capture_method(capture_response=False)
def create_summary(message: Message[IndexCompleteV1], **_) -> None:
    """
    Transform incoming `Message[IndexCompleteV1]` to one or more
    `Message`, then send them to the event bus.
    Args:
        message (Message[IndexCompleteV1]): message to transform.
        **_ (): dummy placeholder for any kwargs may be passed in.

    Returns:
        None
    """
    logger.info(
        f'create_summary for org_uid={message.content.org_uid}, task_uid='
        f'{message.content.task_uid}'
    )

    entries = []
    for m in transform_message(message):
        try:
            entries.append(
                {
                    'EventBusName': OUTBOUND_EVENT_BUS_NAME,
                    'Source': POWERTOOLS_SERVICE_NAME,
                    'DetailType': "OutboundNotification",
                    'Detail': m.json(),
                }
            )
        except:  # noqa
            logger.exception("Fail to add a entry")
            # ignore

    logger.info(f"Send {len(entries)} events")
    if entries:
        client = boto3.client("events")
        resp = client.put_events(Entries=entries)
        logger.info(resp)


register(msg_cls=Message[IndexCompleteV1], receiver=create_summary)


@tracer.capture_method(capture_response=False)
def record_handler(record: SQSRecord) -> None:
    try:
        # TODO: handler should be in a nested db transaction
        logger.debug("record_handler start")
        obj = json.loads(record.body)
        detail = obj["detail"]
        msg_type_id = Message.parse_msg_type_id(detail)
        s = signal(msg_type_id)
        if s.receivers:
            s.send(detail)
        else:
            logger.info(f"No receiver for {msg_type_id=}")
    except:  # noqa
        if (
            int(record.attributes.approximate_receive_count)
            >= MAX_RECEIVE_COUNT
        ):  # noqa
            # Remove the message from the queue if retried too many times
            logger.exception(
                f"Tried {MAX_RECEIVE_COUNT} times, give up the message"
            )
            # ignore
            return
        raise
    return


@logger.inject_lambda_context()
@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler(capture_response=False)
@middleware_db_connect  # should come before batch_processor
@batch_processor(record_handler=record_handler, processor=processor)
def handler(event, context: LambdaContext):
    return processor.response()
