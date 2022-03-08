FROM public.ecr.aws/lambda/python:3.8

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# Upgrade pip (required by cryptography v3.4 and above, which is a dependency of poetry)
RUN pip install --upgrade pip
RUN pip install poetry

# We are at $LAMBDA_TASK_ROOT(/var/task)
WORKDIR /var/task

COPY . .

RUN poetry config virtualenvs.create false && \
    poetry env info && \
    poetry install

ENTRYPOINT ["pytest"]

