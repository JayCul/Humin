"""Seed demo data: a handful of campaigns spread across regions/products, each
run through several agent cycles so the dashboard opens with a real
trajectory instead of an empty state — and so cross-campaign vector recall
in the 'remember' phase actually has precedent to find.

Usage:
    cd backend
    python scripts/seed.py

The same campaign definitions + seeding routine back the in-app "Load demo
data" button on the Settings page (see app/seed_data.py) — this script and
that button stay in sync by construction.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.repository import get_repository  # noqa: E402
from app.seed_data import run_seed  # noqa: E402


def main() -> None:
    repo = get_repository()
    created = run_seed(repo)
    print("\nSeed complete.")
    print(f"Campaigns: {[c['id'] for c in created]}")


if __name__ == "__main__":
    main()
