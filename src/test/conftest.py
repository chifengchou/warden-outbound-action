import logging
from contextvars import ContextVar
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
    Get the transaction's level counting from the root. The root is at level 1.
    NOTE: transaction may not be active. It may not be in a session.
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


# This stores the level of nested transaction when running a test method.
# It is initialized when the first test method of a class kicks in. Subsequent
# test methods of the same class should be in the same level.
# It is then reset to 0 when all test methods finish.
function_transaction_level: ContextVar[int] = ContextVar(
    'function_transaction_level', default=0
)


def restart_savepoint(session, transaction: SessionTransaction):
    """
    A callback responds sqlAlchemy event "after_transaction_end".
    If the ended transaction is a nested one(2ed or a
    function_transaction_level). It starts another one at the same level.
    """
    level = get_transaction_level(transaction)
    ft_level = function_transaction_level.get()
    if level == 2:
        session.begin_nested()
        logger.info(f"Class scope begin_nested restarts at {level=}")
    elif ft_level == level > 2:
        session.begin_nested()
        logger.info(f"Function scope begin_nested restarts at {level=}")


@pytest.fixture(scope="class", autouse=True)
def class_transaction(db_engine):
    # Setup transaction hierarchy according to this:
    # https://docs.sqlalchemy.org/en/13/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites  # noqa
    # Moreover, instead of a 2-level hierarchy of transactions shown in the
    # link, we will create a 3-level one. This is so that transactional change
    # in class-level fixture is visible to test methods.
    #
    # NOTE: class-level fixtures assume
    #  a. it always starts in a top-level transaction
    #  b. it immediately runs in another top-level transaction after a session
    #     commit/rollback.
    #  c. it can begin_nested.
    #  Therefore, a fixture potentially could:
    #  1. commit/rollback N times
    #  2. nest pairs of begin_nested and commit/rollback for M levels
    #  To allow them, the test framework needs to do the following:
    #  i. For case 1, once a commit/rollback encloses the current 2ed-level
    #     transaction, `restart_savepoint` immediately create another 2ed-level
    #     transaction.
    #  ii. For case 2, `restart_savepoint` is no-op.
    #
    # We don't support a transaction spanning across setup and teardown.
    # I.e. This is supported:
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

    assert function_transaction_level.get() == 0
    # Create a new top-level transaction and 2ed-level nested ones for each
    # class. Everything rolls back when tests in the class finish.
    with db_engine.connect() as connection:
        session_factory.configure(bind=connection)
        transaction = connection.begin()
        session: Session = db_session()
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
            logger.info("All fixtures and test methods in the class finished")
            assert get_transaction_level(session.transaction) == level + 1, (
                "Test class may have begin_nested without commit/rollback or "
                "there is a transaction spanning across setup/teardown"
            )

            # A begin_nested may be triggered by restart_savepoint again.
            # But it will be immediately discarded by transaction.rollback.
            session.close()
            logger.info("Connection-level transaction rollback")
            transaction.rollback()
            function_transaction_level.set(0)


@pytest.fixture(scope="function", autouse=True)
def function_transaction():
    # Make sure each test method in the class in the same
    # function_transaction_level.
    # Rollback function_transaction_level when a test method finishes.
    #
    # NOTE: the test methods assume
    #  a. it always starts in a top-level transaction
    #  b. it immediately runs in another top-level transaction after a
    #     session commit/rollback.
    #  c. it can begin_nested.
    #  Therefore, a test method potentially could:
    #  1. commit/rollback N times
    #  2. nest pairs of begin_nested and commit/rollback for M levels
    #  To allow them, the test framework needs to do the following:
    #  i. Far case 1, once a commit/rollback encloses the current transaction,
    #     `restart_savepoint` immediately create another
    #     function_transaction_level transaction.
    #  ii. For case 2, `restart_savepoint` is no-op.
    session: Session = db_session()
    assert event.contains(session, "after_transaction_end", restart_savepoint)

    # Ensures only the first test method begin_nested from here. Others
    # begin_nested from `restart_savepoint`
    ft_level = function_transaction_level.get()
    if ft_level == 0:
        session.begin_nested()
        level = get_transaction_level(session.transaction)
        logger.info(f"Function scope begin_nested starts at {level=}")
        function_transaction_level.set(level)
        ft_level = level
    else:
        level = get_transaction_level(session.transaction)
        assert (
            ft_level == level
        ), f"Function scope transaction {level}, expected to be {ft_level}"
        logger.debug(f"Function scope begin_nested at {level=}")

    try:
        yield session
    finally:
        # Ensure that any begin_nested in the test method has
        # its commit/rollback counterpart.
        assert (
            get_transaction_level(session.transaction) == ft_level
        ), "Test function may have begin_nested without commit/rollback"
        session.rollback()
