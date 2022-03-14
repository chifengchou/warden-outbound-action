from typing import Callable, Dict

from aws_lambda_powertools import Logger
from aws_lambda_powertools.middleware_factory import lambda_handler_decorator
from horangi.models.core import init_database_engine, transaction
from sqlalchemy.pool import NullPool

from constant import SQL_ECHO

from .db import get_database_connection_url

logger = Logger(child=True)


@lambda_handler_decorator
def middleware_db_connect(handler: Callable, event: Dict, context: Dict):
    """
    Middleware that resolves db credential and sets up the db engine. Then
    wraps handler in a transaction.
    NOTE:
        1. This should come before any db middleware that needs a db session.
        2. the handler is responsible for `session.commit()` itself.
    """
    # Initialize db engine and configure session_factory.
    # Do it here instead of doing globally so that any error can be captured
    # by logger.
    init_database_engine(
        get_database_connection_url(), echo=SQL_ECHO, poolclass=NullPool
    )
    with transaction():
        return handler(event, context)
