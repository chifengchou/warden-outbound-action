import json
import os
from functools import lru_cache

from aws_lambda_powertools import Logger
from horangi import IS_AWS, PLATFORM_FN_SECRET, get_lambda_client

logger = Logger(child=True)


@lru_cache(maxsize=1)
def get_database_connection_url():
    """Returns the database connection URL, injecting password retrieved
    via secrets manager if we're running in an lambda environment.
    """
    if IS_AWS:
        secret_key = os.environ.get('DATABASE_PASSWORD_SECRET_KEY')
        db_password = get_secrets(secret_key, PLATFORM_FN_SECRET)
        db_host = os.environ.get('DATABASE_HOST')
        db_name = os.environ.get('DATABASE_NAME')
        db_user = os.environ.get('DATABASE_USERNAME')
        db_url = f'postgresql://{db_user}:{db_password}@{db_host}/{db_name}'
        logger.debug(f"{db_user=}, {db_host=}, {db_name}")
        return db_url
    else:
        # TODO: IS_SAM_LOCAL

        db_host = os.environ.get('DATABASE_HOST', 'localhost:5432')
        # TODO:
        logger.debug(f"{db_host=}")
        return f'postgresql://admin:password@{db_host}/horangi'


@lru_cache
def get_secrets(
    secret_key,
    function_name,
):
    """To be used for all that need to call this lamda for secrets
    param string would look something like:

    `/tgr/{ENVIRONMENT_MODE}/{ENVIRONMENT_ID}/platform/
    ssm/email-provider-api-key`

    You can include the `ENVIRONMENT_MODE` & `ENVIRONMENT_ID` placeholders
    in the `secret_key` which gets automatically replaced.
    """
    logger.debug(f"{function_name=}, {secret_key=}")
    pay_load = {'ParameterNames': [secret_key]}
    pay_load_string_byte = json.dumps(pay_load).encode()
    response = get_lambda_client().invoke(
        FunctionName=function_name, Payload=pay_load_string_byte
    )
    response_payload = response['Payload']
    response_loaded = json.loads(response_payload.read())[secret_key]
    return response_loaded
