#!/usr/bin/env python
"""Build tasks/banking77.json from the BANKING77 intent-classification dataset.

Source: PolyAI-LDN/task-specific-datasets (CC BY 4.0). Casanueva et al.,
"Efficient Intent Detection with Dual Sentence Encoders", NLP4ConvAI 2020.
https://github.com/PolyAI-LDN/task-specific-datasets

Reshapes a random sample of the test split into this repo's task schema: one
Choice question ("intent") with all 77 categories as criteria, and an
`expected` ground-truth label per ticket so the benchmark can also score
accuracy, not just cost/latency.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TRAIN_URL = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/train.csv"
TEST_URL = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv"
CATEGORIES_URL = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/categories.json"


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url) as resp:  # noqa: S310 - fixed, known URLs
        return resp.read().decode("utf-8")


def _load_rows(csv_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=30, help="number of tickets to sample")
    parser.add_argument(
        "--split", choices=["train", "test"], default="test",
        help="BANKING77 split to sample from (test = held-out, recommended)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=str(REPO_ROOT / "tasks" / "banking77.json"))
    args = parser.parse_args()

    categories = json.loads(_fetch(CATEGORIES_URL))
    rows = _load_rows(_fetch(TRAIN_URL if args.split == "train" else TEST_URL))

    rng = random.Random(args.seed)
    sample = rng.sample(rows, min(args.n, len(rows)))

    criteria = {label: label.replace("_", " ") for label in categories}

    task = {
        "task_id": "banking77",
        "description": (
            "BANKING77 intent classification (Casanueva et al., 2020, CC BY 4.0): "
            "one Choice judgment per ticket picking the customer's intent out of "
            "77 banking-specific categories. Sampled from the "
            f"{args.split} split, seed={args.seed}, n={len(sample)}. "
            "Source: https://github.com/PolyAI-LDN/task-specific-datasets"
        ),
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "Which banking intent best matches this customer query?",
                "criteria": criteria,
            }
        },
        "tickets": [
            {
                "id": f"b77-{i}",
                "state": row["text"],
                "expected": {"intent": row["category"]},
            }
            for i, row in enumerate(sample)
        ],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    print(f"Wrote {len(sample)} tickets, {len(categories)} intent categories -> {out_path}")


if __name__ == "__main__":
    main()
