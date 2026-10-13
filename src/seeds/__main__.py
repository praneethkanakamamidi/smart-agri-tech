"""
Seed reference data:  python -m src.seeds [--dry-run] [--only lookups,roles,states,districts] [--json]

Run after `alembic upgrade head` when setting up or updating an environment.
Exit codes: 0 success, 1 seeding failed (rolled back), 2 invalid seed data / arguments.
"""
import argparse
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import src.data_models.registry  # noqa: F401  (resolve model relationships)
from src.seeds.seeder import DATASETS, Seeder, SeedError, SeedValidationError, load_seed_data, results_as_dict


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.seeds", description="Seed static reference data (idempotent).")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change, then roll back.")
    parser.add_argument("--only", help=f"Comma-separated datasets: {','.join(DATASETS)} (default: all).")
    parser.add_argument("--database-url", help="SQLAlchemy URL (default: built from POSTGRES_* env vars).")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON.")
    parser.add_argument("--verbose", action="store_true", help="List every inserted/updated row.")
    args = parser.parse_args(argv)

    try:
        data = load_seed_data()
    except SeedValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    datasets = tuple(s.strip() for s in args.only.split(",") if s.strip()) if args.only else None
    if datasets and set(datasets) - set(DATASETS):
        print(f"ERROR: unknown dataset(s) {sorted(set(datasets) - set(DATASETS))}; choose from {', '.join(DATASETS)}",
              file=sys.stderr)
        return 2

    if args.database_url:
        url = args.database_url
    else:
        from src.db_connections.database import SQLALCHEMY_DATABASE_URL as url
    engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as session:
            results = Seeder(session, data).run(datasets, dry_run=args.dry_run)
    except SeedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    if args.json:
        print(json.dumps({"dry_run": args.dry_run, "checksum": data["checksum"], "results": results_as_dict(results)}, indent=2))
    else:
        mode = "DRY RUN (rolled back)" if args.dry_run else "applied"
        print(f"Reference data {mode}. Seed data checksum {data['checksum'][:12]}")
        for r in results:
            print(f"  {r.name:<10} inserted={r.inserted:<4} updated={r.updated:<4} unchanged={r.unchanged}")
            if args.verbose:
                for line in r.details:
                    print(f"      {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
