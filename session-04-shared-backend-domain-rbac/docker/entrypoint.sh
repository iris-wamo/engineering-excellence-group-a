#!/usr/bin/env sh
set -e

# Run database migrations on container startup if RUN_MIGRATIONS is set to true
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "Running database migrations..."
    uv run alembic upgrade head
fi

# Replace process with main command (e.g. uvicorn) as PID 1 for graceful shutdown
exec "$@"
