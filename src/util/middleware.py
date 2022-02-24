from typing import Callable, Dict

from aws_lambda_powertools import Logger
from aws_lambda_powertools.middleware_factory import lambda_handler_decorator
from horangi.models.core import init_database_engine
from sqlalchemy.pool import NullPool

from constant import SERVICE, SQL_ECHO

from .db import get_database_connection_url

logger = Logger(SERVICE)


@lambda_handler_decorator
def middleware_db_connect(handler: Callable, event: Dict, context: Dict):
    """
    Middleware that resolves db credential and sets up the db engine
    NOTE: This should come before any db middleware that needs a db session.
    """
    # Initialize db engine here instead of globally so that any error can
    # be captured by logger.
    # However, this means that subsequent invocation of the same lambda
    # container won't share the same connection pool if we are using one.
    db_engine = init_database_engine(
        get_database_connection_url(), echo=SQL_ECHO, poolclass=NullPool
    )
    with db_engine.connect() as connection:
        with connection.begin():
            return handler(event, context)
