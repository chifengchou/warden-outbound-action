from typing import Iterable, Tuple, List

from aws_lambda_powertools import Logger
from horangi.generated.destination_type import DestinationType
from horangi.models import ActionGroup
from horangi.models.core import session
from horangi.models.storyfier import Destination

from model.destination_configuration import DestinationConfiguration

logger = Logger(child=True)


def query_enabled_destinations(
    action_group: ActionGroup, destination_types: List[DestinationType] = []
) -> Iterable[Tuple[DestinationConfiguration, Destination]]:
    """
    A generator that yields Tuple[DestinationConfig, Destination] of given
    ActionGroup and DestinationType.

    Args:
        action_group (ActionGroup): Action group with Destinations configured
        destination_types (List[DestinationType], optional): Defaults to [].

    Returns:
        Iterable[Tuple[DestinationConfiguration, Destination]]
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
            query = (
                session.query(Destination)
                .filter(Destination.uid == destination_uid)
            )
            if destination_types:
                query = query.filter(
                    Destination.destination_type.in_([type.value for type in destination_types])
                )
            destination = query.one_or_none()

            if not destination:
                logger.warning(f'No destination for {destination_uid=}')
                continue
            yield config, destination
        except Exception:
            logger.exception(f"Fail to process {dc}")
            # ignored
            continue
