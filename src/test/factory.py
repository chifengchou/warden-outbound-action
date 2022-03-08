"""
A collection of factories of db models to generate fake data for testing.

Differences from `horangi.factory.*`?
1. `horangi.factory.*` assume certain dataset exists in the db.
2. `horangi.factory.*` sets `sqlalchemy_session_persistence = commit` which
   commits every fake record to the db. No rollback unless db resets.
"""
from typing import List, Union

import factory
from factory import fuzzy
from factory.alchemy import SESSION_PERSISTENCE_FLUSH
from horangi import models as db
from horangi.constants import (
    AccountClassification,
    ActionType,
    CheckResult,
    CloudProviderType,
    DestinationType,
    FindingStatus,
    IntegrationType,
    SeverityLevel,
    TaskStatus,
)
from horangi.models.core import session
from horangi.models.storyfier import Destination


class OrgFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.Org
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    name = factory.Sequence(lambda n: f'test{n} org name')
    short_name = factory.Sequence(lambda n: f'test{n} org short name')
    classification = AccountClassification.business.name

    @classmethod
    def create_helper(cls) -> db.Org:
        return cls.create()

    @classmethod
    def batch_helper(cls, size: int) -> List[db.Org]:
        return cls.create_batch(size=size)


class FindingsDefinitionFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.FindingsDefinition
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    findings_type = 'cloud_scan'
    findings_definition_name = factory.sequence(
        lambda n: f"custom/some_uuid_{n:05}"
    )  # noqa
    findings_subtype = 'aws'
    title = factory.sequence(lambda n: f"title {n:05}")
    description = factory.sequence(lambda n: f"description {n:05}")
    recommendation = factory.sequence(lambda n: f"recommendation {n:05}")
    implication = factory.sequence(lambda n: f"implication {n:05}")
    summary = factory.sequence(lambda n: f"summary {n:05}")
    references = factory.sequence(lambda n: f"references {n:05}")
    version = 1
    is_default = True
    status = 'approved'
    original_severity = 1
    created_by = factory.Faker('uuid4')
    updated_by = factory.SelfAttribute("created_by")

    @classmethod
    def create_helper(cls) -> db.FindingsDefinition:
        return cls.create()

    @classmethod
    def batch_helper(cls, size: int) -> List[db.FindingsDefinition]:
        return cls.create_batch(size=size)


class ScanFindingsDefinitionFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.ScanFindingsDefinition
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    title = factory.sequence(lambda n: f"title {n:05}")

    findings_type = 'cloud_scan'
    findings_definition_name = factory.sequence(
        lambda n: f"cloud_scan/aws/some_service/{n:05}"
    )
    findings_subtype = 'aws'
    original_severity = 1  # low

    @classmethod
    def create_helper(cls) -> db.ScanFindingsDefinition:
        return cls.create()

    @classmethod
    def batch_helper(cls, size: int) -> List[db.ScanFindingsDefinition]:
        return cls.create_batch(size=size)


class ScanFindingsDefinitionMappingFactory(
    factory.alchemy.SQLAlchemyModelFactory
):  # noqa
    class Meta:
        model = db.ScanFindingsDefinitionMapping
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    findings_definition = factory.SubFactory(FindingsDefinitionFactory)
    scan_findings_definition = factory.SubFactory(
        ScanFindingsDefinitionFactory
    )  # noqa
    status = 'approved'
    created_by = factory.Faker('uuid4')
    updated_by = factory.SelfAttribute("created_by")

    @classmethod
    def create_helper(cls) -> db.ScanFindingsDefinitionMapping:
        return cls.create()

    @classmethod
    def batch_helper(cls, size: int) -> List[db.ScanFindingsDefinitionMapping]:
        return cls.create_batch(size=size)


class ActionGroupFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.ActionGroup
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    action_group_type = ActionType.cloud_scan.value
    is_enabled = True
    is_hidden = True
    name = factory.Faker('name')  # generates a random name
    schedule = "0 1 * * MON"

    @classmethod
    def create_helper(cls, org_uid) -> db.ActionGroup:
        return cls.create(org_uid=org_uid)

    @classmethod
    def batch_helper(cls, *, size: int, org_uid) -> List[db.ActionGroup]:
        return cls.create_batch(size=size, org_uid=org_uid)


class ContainerServicesTaskFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.Task
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    # uid and task_uid are different
    task_uid = factory.Faker('uuid4')
    last_action_status = TaskStatus.COMPLETED.value
    priority = 2

    @classmethod
    def create_helper(cls, action_uid) -> db.Task:
        action = session.query(db.Action).get(action_uid)
        return cls.create(
            org_uid=action.org_uid,
            action_group_uid=action.action_group_uid,
            action_uid=action.uid,
            action_type=action.action_type,
        )

    @classmethod
    def batch_helper(cls, *, size: int, action_uid) -> List[db.Task]:
        return cls.create_batch(size=size, action_uid=action_uid)


class ChecksStatFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.ChecksStat
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    compliance_standard = 'CIS'

    @classmethod
    def create_helper(cls, action_uid, task_uid=None) -> db.ChecksStat:
        action = session.query(db.Action).get(action_uid)
        if task_uid is None:
            task_uid = action.last_task_uid
        return cls.create(
            org_uid=action.org_uid,
            action_group_uid=action.action_group_uid,
            action_uid=action.uid,
            task_uid=task_uid,
        )

    @classmethod
    def batch_helper(
        cls, *, size: int, action_uid, task_uid=None
    ) -> List[db.ChecksStat]:
        action = session.query(db.Action).get(action_uid)
        if task_uid is None:
            task_uid = action.last_task_uid
        return cls.create_batch(
            size=size, action_uid=action_uid, task_uid=task_uid
        )


class ActionFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.Action
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    action_type = ActionType.cloud_scan.value
    target = factory.Sequence(lambda n: f"target-{n}")
    target_name = factory.Sequence(lambda n: f"target-{n}-name")
    is_enabled = True
    is_verified = True
    is_allowed = True
    status = "PENDING"

    @classmethod
    def create_helper(cls, action_group_uid) -> db.Action:
        action_group = session.query(db.ActionGroup).get(action_group_uid)
        return cls.create(
            org_uid=action_group.org_uid, action_group_uid=action_group_uid
        )

    @classmethod
    def batch_helper(cls, *, size: int, action_group_uid) -> List[db.Check]:
        return cls.create_batch(size=size, action_group_uid=action_group_uid)

    @factory.post_generation
    def create_last_task(obj, create, extracted, **kwargs):
        """
        Last task can be parameterized, e.g.
        ```
        ActionFactory(
            create_last_task__last_action_status='SPAWNING',
            create_last_task__created_at=now()
        )
        ```
        """
        # STRATEGY must be create otherwise we won't get obj.uid
        assert create

        # default
        params = {
            'last_action_status': 'COMPLETED',
        }
        params.update(kwargs)
        task = ContainerServicesTaskFactory.create_helper(obj.uid)
        obj.last_task_uid = task.uid
        ChecksStatFactory.create_helper(obj.uid)


class FindingsFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.Finding
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    action_type = ActionType.cloud_scan.value

    computed_severity = fuzzy.FuzzyChoice(
        [severity.value for severity in SeverityLevel]
    )
    computed_status = fuzzy.FuzzyChoice(
        [status.value for status in FindingStatus]
    )
    signature = fuzzy.FuzzyText()

    @classmethod
    def create_helper(
        cls,
        *,
        action_uid,
        fd_uid,
        task_uid=None,
    ) -> db.Finding:
        action = session.query(db.Action).get(action_uid)
        if task_uid is None:
            task_uid = action.last_task_uid
        return cls.create(
            org_uid=action.org_uid,
            action_group_uid=action.action_group_uid,
            action_uid=action.uid,
            task_uid=task_uid,
            findings_definition_uid=fd_uid,
        )

    @classmethod
    def batch_helper(
        cls,
        *,
        size: int,
        action_uid,
        fd_uid,
        task_uid=None,
    ) -> List[db.Finding]:
        action = session.query(db.Action).get(action_uid)
        if task_uid is None:
            task_uid = action.last_task_uid
        return cls.create_batch(
            size=size,
            org_uid=action.org_uid,
            action_group_uid=action.action_group_uid,
            action_uid=action.uid,
            task_uid=task_uid,
            findings_definition_uid=fd_uid,
        )


class ChecksFactory(factory.alchemy.SQLAlchemyModelFactory):
    """
    NOTE: It does not update ChecksStat and CheckHistory
    """

    class Meta:
        model = db.Check
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    class Params:
        region = fuzzy.FuzzyChoice(['region_1', 'region_2', 'region_3'])
        resource_type = fuzzy.FuzzyChoice(['storage', 'vm', 'database'])
        resource_id = factory.sequence(lambda n: f"id-{n:05}")
        resource_gid = factory.lazy_attribute_sequence(
            lambda o, n: f"{o.provider_type}:{o.resource_type}:{o.resource_id}"
        )

    standards = fuzzy.FuzzyChoice(
        [
            ['cis-aws:1.2'],
            ['cis-aws:1.4', 'mas-trm:1.1.3'],
            ['mas-trm:1.5'],
        ]
    )
    provider_type = CloudProviderType.aws.value

    @factory.lazy_attribute
    def params(self):
        return {
            'region': self.region,
            'resource_type': self.resource_type,
            'resources': [
                {
                    'gid': self.resource_gid,
                    'id': self.resource_id,
                }
            ],
        }

    @factory.lazy_attribute
    def finding_uid(self):
        if CheckResult(self.result) == CheckResult.fail:
            finding = FindingsFactory.create_helper(
                action_uid=self.action_uid,
                fd_uid=self.findings_definition_uid,
                task_uid=self.task_uid,
            )
            return finding.uid
        else:
            return None

    @classmethod
    def create_helper(
        cls,
        *,
        action_uid,
        fd_uid,
        task_uid=None,
        result: Union[CheckResult, int] = CheckResult.pass_,
    ) -> db.Check:
        action = session.query(db.Action).get(action_uid)
        if task_uid is None:
            task_uid = action.last_task_uid

        return cls.create(
            org_uid=action.org_uid,
            action_group_uid=action.action_group_uid,
            action_uid=action.uid,
            task_uid=task_uid,
            findings_definition_uid=fd_uid,
            result=CheckResult(result).value,
        )

    @classmethod
    def batch_helper(
        cls,
        *,
        size: int,
        action_uid,
        fd_uid,
        result: Union[CheckResult, int] = CheckResult.pass_,
    ) -> List[db.Check]:
        action = session.query(db.Action).get(action_uid)

        return cls.create_batch(
            size,
            org_uid=action.org_uid,
            action_group_uid=action.action_group_uid,
            action_uid=action.uid,
            task_uid=action.last_task_uid,
            findings_definition_uid=fd_uid,
            result=CheckResult(result).value,
        )


class IntegrationFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = db.Integration
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    @classmethod
    def create_helper(
        cls, org_uid, integration_type: IntegrationType
    ) -> db.Integration:
        return cls.create(
            org_uid=org_uid, integration_type=integration_type.value
        )

    @classmethod
    def batch_helper(
        cls, *, size: int, org_uid, integration_type: IntegrationType
    ) -> List[db.Integration]:
        return cls.create_batch(
            size=size, org_uid=org_uid, integration_type=integration_type
        )


class DestinationFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Destination
        sqlalchemy_session = session
        sqlalchemy_session_persistence = SESSION_PERSISTENCE_FLUSH

    name = factory.Sequence(lambda n: f'test{n} destination')

    @classmethod
    def create_helper(
        cls,
        integration_uid,
        destination_type: DestinationType,
    ) -> Destination:
        integration = session.query(db.Integration).get(integration_uid)
        return cls.create(
            org_uid=integration.org_uid,
            integration_uid=integration_uid,
            destination_type=destination_type.value,
        )

    @classmethod
    def batch_helper(
        cls, *, size: int, integration_uid, destination_type: DestinationType
    ) -> List[Destination]:
        integration = session.query(db.Integration).get(integration_uid)
        return cls.create_batch(
            size=size,
            org_uid=integration.org_uid,
            integration_uid=integration_uid,
            destination_type=destination_type.value,
        )
