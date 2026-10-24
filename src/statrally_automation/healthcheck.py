"""Dependency-free automation smoke check. No market claims or private data."""
from datetime import datetime, timezone


def run():
    return {"status": "ok", "utc": datetime.now(timezone.utc).isoformat(), "mode": "scaffold_only"}


if __name__ == "__main__":
    print(run())
