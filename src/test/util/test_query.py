from test.factory import (
    ActionGroupFactory,
    DestinationFactory,
    IntegrationFactory,
    OrgFactory,
)
from typing import ClassVar, List

from horangi.constants import DestinationType, IntegrationType
from horangi.models import ActionGroup, Integration, Org
from horangi.models.core import session
from horangi.models.storyfier import Destination
from sqlalchemy.orm.attributes import flag_modified

from model.destination_configuration import DestinationConfiguration
from util.query import query_enabled_destinations


class TestQuery:
    org: ClassVar[Org]
    integrations: ClassVar[List[Integration]]
    destinations: ClassVar[List[Destination]]
    action_group: ClassVar[ActionGroup]

    @classmethod
    def setup_class(cls):
        cls.org = OrgFactory.create_helper()
        cls.integrations = [
            IntegrationFactory.create_helper(
                cls.org.uid, IntegrationType.slack
            ),
            IntegrationFactory.create_helper(
                cls.org.uid, IntegrationType.aws_sns
            ),
        ]
        cls.destinations = DestinationFactory.batch_helper(
            size=2,
            integration_uid=cls.integrations[0].uid,
            destination_type=DestinationType.slack,
        ) + DestinationFactory.batch_helper(
            size=2,
            integration_uid=cls.integrations[1].uid,
            destination_type=DestinationType.aws_sns,
        )
        # DestinationConfiguration: first 2 are slask, last 2 are aws_sns,
        dcs = [
            # for slack
            DestinationConfiguration(
                destination_uid=cls.destinations[0].uid,
            ),
            DestinationConfiguration(
                destination_uid=cls.destinations[1].uid,
                is_enabled=False,
            ),
            # for sns
            DestinationConfiguration(
                destination_uid=cls.destinations[2].uid,
                filters={"severities": [0, 1, 2, 3, 4]},
            ),
            DestinationConfiguration(
                destination_uid=cls.destinations[3].uid,
                is_enabled=False,
            ),
        ]

        cls.action_group = ActionGroupFactory.create_helper(cls.org.uid)
        cls.action_group.meta["destination_configuration"] = list(
            map(lambda dc: dc.dict(), dcs)
        )
        flag_modified(cls.action_group, "meta")
        session.commit()

    def test_query_enabled_destinations(self):
        result = list(
            query_enabled_destinations(
                TestQuery.action_group, [DestinationType.aws_sns]
            )
        )
        assert len(result) == 1
        assert result[0][1].uid == TestQuery.destinations[2].uid
