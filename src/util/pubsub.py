import base64
import json
import logging
from concurrent import futures
from typing import Callable, Dict

from aws_lambda_powertools import Logger
from boto3.session import Session
from cryptography.fernet import Fernet
from google.cloud import pubsub_v1
from google.oauth2.service_account import Credentials
from horangi.signals.message import Message

from constant import LOG_LEVEL
from model import PubSubSummaryInputV1

session = Session()
logger = Logger(level=logging.getLevelName(LOG_LEVEL))

kms_client = session.client('kms')


def get_callback(
    publish_future: pubsub_v1.publisher.futures.Future, data: str
) -> Callable[[pubsub_v1.publisher.futures.Future], None]:
    """Wrap message data in the context of the callback function."""

    def callback(
        publish_future: pubsub_v1.publisher.futures.Future,
    ) -> None:
        try:
            # Wait 60 seconds for the publish call to succeed.
            logger.info(
                f"GCP published message now has message ID: {publish_future.result(timeout=60)}"
            )
        except Exception as e:
            logger.warning(f"Failed to publish message {data}: {e}")

    return callback


def _decrypt_credential(credentials: Dict):
    encrypted_data_key = bytes(base64.b64decode(credentials["encrypted_data_key"]))
    encrypted_cred = bytes(str.encode(credentials["encrypted_credentials"]))

    response = kms_client.decrypt(
        CiphertextBlob=encrypted_data_key,
    )

    f = Fernet(base64.b64encode(response["Plaintext"]))

    credentials = json.loads(bytes.decode(f.decrypt(encrypted_cred)))
    return credentials


def send_pubsub_message(message: Message[PubSubSummaryInputV1]):
    encrypted_credentials = message.content.encrypted_credentials
    project_id = message.content.project_id
    topic_id = message.content.topic_id

    credentials = Credentials.from_service_account_info(
        _decrypt_credential(encrypted_credentials)
    )
    publisher = pubsub_v1.PublisherClient(credentials=credentials)

    topic_path = publisher.topic_path(project_id, topic_id)
    payload = message.content.summary.json()
    future = publisher.publish(topic_path, payload.encode("utf-8"))
    future.add_done_callback(get_callback(future, payload))
    futures.wait([future], return_when=futures.ALL_COMPLETED)
