import logging
from typing import List

import alembic
import pytest
from horangi import IS_AWS
from horangi.models.core import (
    get_database_admin_connection_url,
    init_database_engine,
    metadata,
)
from horangi.models.core import session as db_session
from horangi.models.core import session_factory
from sqlalchemy import event
from sqlalchemy.orm.session import Session, SessionTransaction

from constant import SRC_DIR
from util.db import get_database_connection_url

logger = logging.getLogger(__name__)


# The tests must be run under SRC_DIR(working dir). This is because the
# path to migration scripts written in alembic.ini is a relative path.
ALEMBIC_INI = (
    SRC_DIR / "tgr-backend-common" / "horangi" / "migrations" / "alembic.ini"
)  # noqa


def create_database(
    engine,
    meta_data,
    *,
    alembic_ini: str,
    alembic_version: str = 'head',
    alembic_options: List[str] = None,
):
    """
    Bootstraps the database with the required schema and stamp the migrations.
    NOTE: tgr-backend-common/horangi/migrations are not included when
      tgr-backend-common is installed as an editable package by poetry.
      That's why we pass in the path to alembic.ini
    """
    # Extension setup.
    engine.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    # This will fail if database already exist.
    meta_data.create_all(bind=engine, checkfirst=False)
    session_factory.configure(bind=engine)
    if alembic_ini:
        stamp_database(
            alembic_ini=alembic_ini,
            alembic_version=alembic_version,
            alembic_options=alembic_options,
        )


def stamp_database(
    alembic_ini: str,
    *,
    alembic_version: str = 'head',
    alembic_options: List[str] = None,
):
    argv = ['-c', alembic_ini]
    if alembic_options:
        argv += alembic_options
    argv += ['stamp', alembic_version]
    alembic.config.main(argv=argv)


@pytest.fixture(scope="session", autouse=True)
def db_engine():
    """
    Resets DB to original state and bind session_factory.
    """
    assert not IS_AWS, pytest.fail('This fixture should not be run in AWS.')

    # bind admin_db_engine to session_factory to perform admin tasks
    admin_db_engine = init_database_engine(
        get_database_admin_connection_url(), echo=False
    )
    metadata.drop_all(admin_db_engine)
    # NOTE: We don't use horangi.models.core.create_database.
    #  This is to fix the problem of "No config file '.venv/lib/python3.8/
    #  site-packages/horangi/migrations/alembic.ini' found".
    create_database(
        admin_db_engine,
        metadata,
        alembic_ini=str(ALEMBIC_INI),
        alembic_options=['-n', 'storyfier'],
    )
    # bind db_engine to session_factory to perform tests
    yield init_database_engine(get_database_connection_url(), echo=False)


def get_transaction_level(transaction: SessionTransaction):
    """
    Get the transaction's level counting from the root. The root(top level) is
    at level 1.
    NOTE: `transaction` may not be active. It also may not be in a session.
    """
    level = 1
    if not transaction.nested:
        return level
    assert transaction.parent, "Nested transaction should have parent"
    current = transaction.parent
    while current:
        level += 1
        current = current.parent

    return level


def restart_savepoint(session, transaction: SessionTransaction):
    """
    A callback responds sqlAlchemy event "after_transaction_end".
    It starts another one if the ended transaction is a 2ed or 3rd-level.
    """
    level = get_transaction_level(transaction)
    if level == 2:
        session.begin_nested()
        logger.info(f"Class scope begin_nested restarts at {level=}")
    elif level == 3:
        session.begin_nested()
        logger.info(f"Method scope begin_nested restarts at {level=}")


@pytest.fixture(scope="class", autouse=True)
def class_transaction(db_engine):
    # Setup transaction hierarchy.
    # Ref: https://docs.sqlalchemy.org/en/13/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites  # noqa
    #
    # Along with `method_transaction`, we actually create a 3-level hierarchy
    # instead of a 2-level one shown in the reference. This is so that
    # transactional change in class-level fixtures is visible to test methods.
    #
    # NOTE: a class-level fixture(incl. setup_class/teardown_class) assumes:
    #  a. it is always in a top-level transaction
    #  b. it is immediately in another top-level transaction after one is
    #     commit/rollback.
    #  c. it can begin_nested but must have commit/rollback counterpart.
    #  We create a 2ed-level transaction for a test class to allow fixtures to
    #  use it as if it is a top-level. Whenever a 2ed-level is commit/rollback,
    #  `restart_savepoint` immediately create another one. At the end, we
    #  rollback the top-level transaction.
    #  By doing so, fixtures won't be able to commit/rollback on the top-level
    #  transaction so nothing is persisted to the DB.
    #
    # We don't support a transaction spanning across setup and teardown.
    # I.e. This is ok:
    # ```
    # @pytest.fixture(scope="class")
    # def foo():
    #     session.begin_nested()
    #     session.commit()
    #     yield
    # ```
    # whereas this is NOT
    # ```
    # @pytest.fixture(scope="class")
    # def foo():
    #     session.begin_nested()  # setup
    #     yield
    #     session.commit()  # teardown, intend to enclosing begin_nested
    # ```

    # Create a new top-level transaction and 2ed-level nested ones for each
    # class. Everything rolls back when tests in the class finish.
    logger.info(">> class_transaction setup")
    with db_engine.connect() as connection:
        session_factory.configure(bind=connection)
        transaction = connection.begin()
        session: Session = db_session()
        # Must not be in autocommit mode(default is False), so session is
        # implicitly in a top-level transaction.
        assert not session.autocommit, "Session must not in autocommit mode"
        try:
            session.begin_nested()
            level = get_transaction_level(session.transaction)
            assert level == 2
            logger.info(f"Class scope begin_nested starts at {level=}")
            # Unlike top-level transactions, a nested transactions does not
            # auto re-start after an enclosing commit/rollback. So we do it by
            # ourselves.
            event.listen(session, "after_transaction_end", restart_savepoint)
            yield session
        finally:
            logger.info("<< class_transaction teardown")
            session.close()
            # A 2ed-level will be start again by `restart_savepoint` after
            # `session.close()`. But it is immediately discarded because
            # a new top-level starts.
            logger.info("Connection-level transaction rollback")
            transaction.rollback()


@pytest.fixture(scope="function", autouse=True)
def method_transaction():
    # Make sure each test method in the class in 3rd-level transaction.
    # Rollback when a test method finishes.
    #
    # NOTE: a test method assumes:
    #  a. it is always in a top-level transaction
    #  b. it is immediately in another top-level transaction after one is
    #     commit/rollback.
    #  c. it can begin_nested but must have commit/rollback counterpart.
    #  We create a 3rd-level transaction to allow a test method to use it as if
    #  it is a top-level. Whenever a 3rd-level is commit/rollback,
    #  `restart_savepoint` immediately create another one. At the end, we
    #  rollback the 2ed-level transaction.
    #  By doing so, a test method
    #  1. won't be able to commit/rollback on the 2ed-level transaction so
    #     any transactional changes won't be visible to other test methods.
    #  2. won't be able to commit/rollback on the top-level transaction so
    #     nothing is persisted to the DB.
    logger.info(">> method_transaction setup")
    session: Session = db_session()
    assert event.contains(session, "after_transaction_end", restart_savepoint)

    # Ensures only the first test method begin_nested from here. Others
    # begin_nested from `restart_savepoint`

    session.begin_nested()
    level = get_transaction_level(session.transaction)
    logger.info(f"Method scope begin_nested starts at {level=}")
    assert level == 3, f"Method scope transaction {level} != 3"

    parent_transaction = session.transaction.parent

    try:
        yield session
    finally:
        logger.info("<< method_transaction teardown")
        # Ensure that any begin_nested in the test method has
        # its commit/rollback counterpart.
        assert (
            get_transaction_level(session.transaction) == 3
        ), "Test method may have begin_nested without commit/rollback"
        # A 3rd-level will be start again by `restart_savepoint` after
        # `parent_transaction.rollback()`. But it is immediately discarded
        # because a new 2ed-level starts.
        parent_transaction.rollback()
