#!/bin/sh
# Container entrypoint.
#   serve     run the API with gunicorn + uvicorn workers (default)
#   migrate       apply database migrations (alembic upgrade head) and create the LangGraph
#                 checkpoint tables (python -m src.agents.checkpointer setup)
#   seed          load reference data (python -m src.seeds); extra args are passed through, e.g. "seed --dry-run"
#   worker        run background jobs in a dedicated process (set SCHEDULER_ENABLED=false on the API)
#   agent-worker  drive agent workflows in a dedicated process (set AGENT_WORKER_ENABLED=false on the API)
#   <other>       run any other command, e.g. "pytest"
# Migrations and seeding are explicit deploy steps; they never run implicitly on startup.
set -eu

command="${1:-serve}"
[ "$#" -gt 0 ] && shift

case "$command" in
  serve)
    exec gunicorn main:smart_agri_tech_app -c gunicorn.conf.py "$@"
    ;;
  migrate)
    alembic upgrade head "$@"
    exec python -m src.agents.checkpointer setup
    ;;
  seed)
    exec python -m src.seeds "$@"
    ;;
  worker)
    exec python -m src.core.scheduler "$@"
    ;;
  agent-worker)
    exec python -m src.agents.worker "$@"
    ;;
  *)
    exec "$command" "$@"
    ;;
esac
