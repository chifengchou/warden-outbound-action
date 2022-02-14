import logging
import os
from http import HTTPStatus

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.middleware_factory import lambda_handler_decorator
from horangi import IS_AWS
from horangi import models as db_models
from horangi.models.core import init_database_engine, session, transaction
from sqlalchemy.pool import NullPool

from constant import SERVICE
from db_connect import get_database_connection_url

LOG_LEVEL = os.environ.get('LOG_LEVEL', "INFO")

SQL_ECHO = False if IS_AWS else LOG_LEVEL == "DEBUG"

logger = Logger(service=SERVICE, level=logging.getLevelName(LOG_LEVEL))
logger.info(f"{SERVICE=}, {IS_AWS=}, {LOG_LEVEL=}, {SQL_ECHO=}")


# NOTE: To disable tracing set ENV:
#   POWERTOOLS_TRACE_DISABLED="1"
#   POWERTOOLS_TRACE_MIDDLEWARES="False"
tracer = Tracer(service=SERVICE)
# TODO: metrics need service/namespace/segment/dimension
metrics = Metrics(service=SERVICE)


app = APIGatewayHttpResolver(
    debug=LOG_LEVEL == "DEBUG",
    cors=CORSConfig(
        allow_origin="*",
        max_age=3600,
    ),
)


@lambda_handler_decorator(trace_execution=True)
def middleware_catch_exception(handler, event, context):
    """
    Middleware that handles exceptions not captured by ApiGatewayResolver.
    NOTE: This should be the outmost(top) middleware.

    We should already `route_catch_exception` for routes. This is for
    exceptions might happen in other middlewares
    """
    try:
        return handler(event, context)
    except Exception:
        logger.exception("Service error")
        # It only surfaces limited information to the client. I.e. no
        # stack trace and others in the response.
        # https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-output-format  # noqa
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'headers': {},
            'body': "",
            'isBase64Encoded': False,
        }


@lambda_handler_decorator(trace_execution=True)
def middleware_db_connect(handler, event, context):
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
    with db_engine.connect():
        with transaction():
            return handler(event, context)


@metrics.log_metrics
@logger.inject_lambda_context(
    correlation_id_path=correlation_paths.API_GATEWAY_HTTP
)  # noqa
@tracer.capture_lambda_handler(capture_response=False)
@middleware_catch_exception
@middleware_db_connect
def handler(event, context):
    """
    Args:
        event: API Gateway Lambda Proxy Input Format
            https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format  # noqa
        context: Lambda Context runtime methods and attributes
            https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html  # noqa

    Returns: API Gateway Lambda Proxy Output Format
            https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html  # noqa
    """
    return app.resolve(event, context)


@app.get(".+")
def catch_all_handler():
    logger.info("==========================")
    org = session.query(db_models.Org).get(
        "cfed6f7d-a719-455b-8342-3bd51ab36650"
    )  # noqa
    logger.info(org)


# def handler(event, context):
#    return {
#        "statusCode": 200,
#        "body": "Hello, World! Your request was received at {}.".format(
#            event['requestContext']['time']
#        ),
#    }
