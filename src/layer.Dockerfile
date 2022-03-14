FROM public.ecr.aws/sam/build-python3.8:latest

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

COPY pyproject.toml poetry.lock ./
# tgr-backend-common as an editable dependency needs to be copied over
COPY tgr-backend-common ./tgr-backend-common

# Run these command separately
RUN if [ -f 'poetry.lock' ]; then poetry export --with-credentials --without-hashes --format requirements.txt --output requirements.txt; else echo "poetry.lock not found"; fi
RUN mkdir -p /var/dependency/python && pip install -r requirements.txt -t /var/dependency/python && \
    rm -rf /var/dependency/python/botocore* && rm -rf /var/dependency/python/boto3*
