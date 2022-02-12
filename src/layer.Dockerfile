# NOTE:
# If you update this file, most likely you need to updte pytest.Dockerfile too

FROM public.ecr.aws/lambda/python:3.8
# https://docs.aws.amazon.com/lambda/latest/dg/images-create.html

# https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Lambda-Insights-Getting-Started-docker.html
RUN curl -O https://lambda-insights-extension.s3-ap-northeast-1.amazonaws.com/amazon_linux/lambda-insights-extension.rpm && \
    rpm -U lambda-insights-extension.rpm && \
    rm -f lambda-insights-extension.rpm

# Patch: https://alas.aws.amazon.com/AL2/ALAS-2021-1615.html
# Patch: https://alas.aws.amazon.com/AL2/ALAS-2021-1638.html
RUN yum update -y glibc openldap

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
RUN mkdir -p /var/dependency/python && pip install -r requirements.txt -t /var/dependency/python
