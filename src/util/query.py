from typing import Iterable, Tuple

from aws_lambda_powertools import Logger
from horangi.generated.destination_type import DestinationType
from horangi.models import ActionGroup
from horangi.models.core import session
from horangi.models.storyfier import Destination

from model.destination_configuration import DestinationConfiguration

logger = Logger(child=True)


def query_enabled_destinations(
    action_group: ActionGroup, destination_type: DestinationType
) -> Iterable[Tuple[DestinationConfiguration, Destination]]:
    """
    A generator yields Tuple[DestinationConfig, Destination]
    """
    destination_configurations = action_group.destination_configuration
    if not destination_configurations:
        logger.info(
            f'No destination configuration for action group {action_group.uid}'
        )  # noqa
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
