import json
import logging
import os
import re

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
from horangi.signals.message import Message
from horangi.signals.message_util import register
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

from constant import LOG_LEVEL, SQL_ECHO
from model.sns_summary import SnsSummaryInputV1
from util.middleware import middleware_db_connect

POWERTOOLS_METRICS_NAMESPACE = os.environ.get(
    "POWERTOOLS_METRICS_NAMESPACE", "outbound"
)
POWERTOOLS_SERVICE_NAME = os.environ.get("POWERTOOLS_SERVICE_NAME")

if not POWERTOOLS_SERVICE_NAME:
    if IS_AWS:
        raise AssertionError("env POWERTOOLS_SERVICE_NAME is not set.")
    else:
        POWERTOOLS_SERVICE_NAME = "sender"

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
def send_sns_summary(message: Message[SnsSummaryInputV1], **_) -> None:
    topic_arn = message.content.sns_topic_arn
    m = re.match(r"^arn:aws:sns:([\w-]+):.+$", topic_arn)
    # e.g. m.groups() == ('us-east-1',)
    region = m.group(1)
    logger.info(
        f'send_sns_summary for org_uid={message.content.org_uid}, task_uid='
        f'{message.content.task_uid}, {topic_arn=}, {region=}'
    )
    client = boto3.client("sns", region_name=region)

    summary = message.content.summary.json()
    resp = client.publish(
        Message=summary,
        TopicArn=topic_arn,
    )
    logger.info(resp)


register(msg_cls=Message[SnsSummaryInputV1], receiver=send_sns_summary)


@tracer.capture_method(capture_response=False)
def record_handler(record: SQSRecord) -> None:
    # TODO: handler should be in a nested db transaction
    try:
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
