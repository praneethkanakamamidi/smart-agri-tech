# PostgreSQL 16 with the two extensions the agent layer needs:
#   PostGIS  - radius matching of suppliers (migration 006 creates geography indexes)
#   pgvector - semantic retrieval over listing embeddings
# Used by compose.yml and CI. On managed PostgreSQL enable both extensions instead.
# 16-3.6 is built on Debian trixie; the older 16-3.4 tag is on bullseye, which apt.postgresql.org
# no longer serves, so pgvector can't be installed on it.
FROM postgis/postgis:16-3.6

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
