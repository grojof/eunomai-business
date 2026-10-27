#!/usr/bin/env bash
# IT's command that makes a release ready, called as: APPLY <release folder> <commit>. It lives on the server,
# outside the repository, owned by root. This example is for a Python application run with uv and migrated with
# Alembic; change it to what the application needs.
#
# What it runs from the release (the dependencies, the migrations) is the branch's code: on a test environment, code
# no one has reviewed yet. It runs as the agent's unprivileged user, with only the test environment's credentials.
set -euo pipefail
release="$1"

# The application's configuration on this server: the test database, never production's.
set -a
. /etc/example-project/test.env
set +a

cd "$release"
uv sync --frozen --no-dev
uv run --frozen alembic upgrade head
# The restart is not this script's: restart-on-deploy@<name>.path restarts the application when the release is
# current, so the agent needs no right over services.
