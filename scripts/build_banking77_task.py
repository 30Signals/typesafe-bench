#!/usr/bin/env python
"""Build tasks/banking77.json from the BANKING77 intent-classification dataset.

Source: PolyAI-LDN/task-specific-datasets (CC BY 4.0). Casanueva et al.,
"Efficient Intent Detection with Dual Sentence Encoders", NLP4ConvAI 2020.
https://github.com/PolyAI-LDN/task-specific-datasets

Reshapes a random sample of the test split into this repo's task schema: one
Choice question ("intent") with all 77 categories as criteria, and an
`expected` ground-truth label per ticket so the benchmark can also score
accuracy, not just cost/latency.

Each criterion is more than just the label name: it's paired with a few real
example queries pulled from the train split, since several categories are
near-synonyms (e.g. order_physical_card vs. get_physical_card,
beneficiary_not_allowed vs. failed_transfer/declined_transfer) that a bare
label name alone doesn't disambiguate -- every benchmarked model gets these
same examples, so it's still an apples-to-apples comparison.
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


EXAMPLES_PER_LABEL = 3


def _build_criteria(
    categories: list[str],
    train_rows: list[dict[str, str]],
    exclude_texts: set[str],
    seed: int,
) -> dict[str, str]:
    by_label: dict[str, list[str]] = {}
    for row in train_rows:
        if row["text"] in exclude_texts:
            continue
        by_label.setdefault(row["category"], []).append(row["text"])

    rng = random.Random(seed)  # separate from the ticket-sampling rng
    criteria = {}
    for label in categories:
        pool = by_label.get(label, [])
        examples = rng.sample(pool, min(EXAMPLES_PER_LABEL, len(pool)))
        description = label.replace("_", " ")
        if examples:
            description += " -- e.g. " + "; ".join(f'"{e}"' for e in examples)
        criteria[label] = description
    return criteria


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
    train_rows = _load_rows(_fetch(TRAIN_URL))
    rows = train_rows if args.split == "train" else _load_rows(_fetch(TEST_URL))

    # Ticket sampling uses its own rng, seeded and consumed exactly as before
    # this function existed -- so the same --seed still selects the same
    # tickets even after adding example-based criteria below (that uses a
    # separate rng), keeping before/after comparisons apples-to-apples.
    rng = random.Random(args.seed)
    sample = rng.sample(rows, min(args.n, len(rows)))

    criteria = _build_criteria(
        categories, train_rows, exclude_texts={row["text"] for row in sample}, seed=args.seed
    )

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
