#!/usr/bin/env bash
# NOTE:
# This Script is used by CI/CD to run tests.

# ref: https://github.com/ralish/bash-script-template
set -o errexit  # Exit on most errors (see the manual)
set -o errtrace # Make sure any error trap is inherited
set -o nounset  # Disallow expansion of unset variables
set -o pipefail # Use last non-zero exit code in a pipeline

# Go to the src dir regardless where we are
# AWS CodePipleline doesn't have pushd/popd
ORIGIN_DIR=$(pwd)
cd $(dirname "$0")
cd ..

docker-compose down --remove-orphans
docker-compose up -d
docker build -t tgr-warden-outbound-test -f pytest.Dockerfile .
docker container run --network tgr-horangi-platform -e DATABASE_HOST=database-horangi --rm tgr-warden-outbound-test
docker-compose down --remove-orphans

cd $ORIGIN_DIR
