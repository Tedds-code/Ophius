
# Made in cooperation with ChatGPT
# File: src/astro_health/__main__.py

from pathlib import Path

from astro_health.cli import HealthCLI
from astro_health.database import Database
from astro_health.health_service import HealthService


def main():
    project_root = Path(__file__).resolve().parents[2]
    database_path = project_root / "data" / "astro_health.db"

    database = Database(database_path)
    database.initialize()

    service = HealthService(database)
    cli = HealthCLI(service)

    cli.run()


if __name__ == "__main__":
    main()
