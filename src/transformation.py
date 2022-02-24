import json
import logging
from typing import Any, Dict, Iterable, List, Tuple

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
from horangi.models import (
    Action,
    CheckHistory,
    FindingsDefinition,
    ScanFindingsDefinitionMapping,
)
from horangi.models.core import session
from horangi.models.storyfier import Destination
from horangi.querybakery.baked_queries import (
    query_check_history_contexts,
    query_filtered_checks,
)
from horangi.signals.message import Message
from horangi.signals.message_storyfier import IndexCompleteV1
from horangi.signals.message_util import register
from pydantic import BaseModel, Field

from constant import LOG_LEVEL, SERVICE, SQL_ECHO
from model.sns_summary import AggregatedByRule, Resource, SnsSummaryV1
from util.eventbus import put_events
from util.middleware import middleware_db_connect

logger = Logger(service=SERVICE, level=logging.getLevelName(LOG_LEVEL))
logger.info(f"{SERVICE=}, {IS_AWS=}, {LOG_LEVEL=}, {SQL_ECHO=}")


# NOTE: To disable tracing set ENV:
#   POWERTOOLS_TRACE_DISABLED="1"
#   POWERTOOLS_TRACE_MIDDLEWARES="False"
tracer = Tracer(service=SERVICE)
# TODO: metrics need service/namespace/segment/dimension
metrics = Metrics(service=SERVICE, namespace="transformation")

# Infra must enable "Report Batch Item Failures"
processor = BatchProcessor(event_type=EventType.SQS)


class DestinationConfiguration(BaseModel):
    """
    DestinationConfiguration models elements in
    ActionGroup.destination_configurations
    """

    destination_uid: str
    is_enabled: bool = False
    # filters for now only supports severities, e.g.
    # `"severities": [ "low", "high" ]`
    filters: Dict[str, Any] = Field(default_factory=dict)


def get_enabled_destination(
    action: Action, destination_type: DestinationType
) -> Iterable[Tuple[DestinationConfiguration, Destination]]:
    """
    A generator yields Tuple[DestinationConfig, Destination]
    """
    if action.action_type != ActionType.cloud_scan.value:
        logger.info(f"Only {ActionType.cloud_scan} is supported")
        return
    destination_configurations = action.action_group.destination_configuration
    if not destination_configurations:
        logger.info(
            f'No destination configuration for action group '
            f'{action.action_group_uid}'
        )
        return

    for dc in destination_configurations:
        try:
            config = DestinationConfiguration.parse_obj(dc)
            destination_uid = config.destination_uid
            if not config.is_enabled:
                logger.info(f"{destination_uid=} is disabled")
                continue
            logger.info(f"Processing {destination_uid=} ")
            destination = (
                session.query(Destination)
                .filter(
                    Destination.uid == destination_uid,
                    Destination.destination_type == destination_type.value,
                )
                .one_or_none()
            )
            if not destination:
                logger.warning(f'No destination for {destination_uid=}')
                continue
            yield config, destination
        except Exception:
            logger.exception(f"Fail to process {dc}")
            # ignored
            continue


def get_aggregated_by_rules(
    org_uid,
    task_uid,
    filters,
) -> List[AggregatedByRule]:
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
    rules: Dict[str, AggregatedByRule] = dict()
    for row in rows:
        if row.resource_gid:
            resource = Resource(
                is_service=False,
                region=row.resource_region,
                service=row._params.get('service'),
                severity=row.severity,
                gid=row.resource_gid,
                note=row.note,
            )
        else:
            resource = Resource(
                is_service=True,
                region=row._params.get('region'),
                service=row._params.get('service'),
                severity=row.severity,
                note=row.note,
            )

        # Only compliance tags
        tags = list(filter(lambda t: t.startswith("compliance:"), row.tags))
        aggregated = rules.get(row.title)
        if aggregated is None:
            aggregated = AggregatedByRule(
                rule=row.title,
                default_severity=row.default_severity,
                resources=[resource],
                tags=tags,
            )
            rules[row.title] = aggregated
        else:
            aggregated.resources.append(resource)

    return list(rules.values())


def create_summary_for_sns(m: Message[IndexCompleteV1], **_) -> None:
    task_uid = m.content.task_uid
    logger.debug(f"create_summary_for_sns for {task_uid=}")
    action: Action = session.query(Action).get(m.content.action_uid)

    msgs = []
    for config, destination in get_enabled_destination(
        action, DestinationType.aws_sns
    ):  # noqa
        try:
            logger.debug(f"Process {destination.uid=}")
            rules = get_aggregated_by_rules(
                action.org_uid, task_uid, config.filters
            )  # noqa
            summary = SnsSummaryV1(
                sns_topic_arn=destination.sns_topic_arn,
                cloud_provider=action.cloud_provider_type,
                action_group_name=action.action_group.name,
                target_name=action.target_name,
                rules=rules,
            )
            msg = Message[SnsSummaryV1](
                msg_type="SnsSummary",
                version="1",
                content=summary,
                # Route to sender
                msg_attrs={"route": "ready_to_send"},
            )
            logger.info(msg)
            msgs.append(msg)
        except Exception:
            logger.exception(
                f"Failed to create summary for {destination.uid}. Continue"
            )
            # ignore

    logger.info(f"Send {len(msgs)} events")
    if msgs:
        resp = put_events(msgs, source="transformation")
        logger.info(resp)


register(msg_cls=Message[IndexCompleteV1], receiver=create_summary_for_sns)


@tracer.capture_method
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
