#!/usr/bin/env python
"""Build tasks/clinc150.json from the CLINC150 intent-classification dataset.

Source: clinc/oos-eval (CC BY 3.0). Larson et al., "An Evaluation Dataset for
Intent Classification and Out-of-Scope Prediction", EMNLP 2019.
https://github.com/clinc/oos-eval

150 intents across 10 broad domains (banking, travel, utility, work, small
talk, meta, etc.), plus an explicit "oos" (out-of-scope) class for queries
that don't match any listed intent -- unlike BANKING77, this directly
exercises the "when should the model say it doesn't know" behavior central
to Jev's calibrated-decision pitch, since a good Choice answer here isn't
just "pick the closest label" but "recognize when nothing fits".

Reshapes a random sample of in-scope + out-of-scope test examples into this
repo's task schema: one Choice question ("intent") with all 150 categories
plus "oos" as criteria, and an `expected` ground-truth label per ticket.
"""
from __future__ import annotations

import argparse
import json
import random
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DATA_URL = "https://raw.githubusercontent.com/clinc/oos-eval/master/data/data_full.json"

OOS_LABEL = "oos"
OOS_DESCRIPTION = (
    "none of the above -- the query does not clearly match any other listed intent"
)


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:  # noqa: S310 - fixed, known URL
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=30, help="number of in-scope tickets to sample")
    parser.add_argument(
        "--oos-n", type=int, default=None,
        help="number of out-of-scope tickets to sample (default: ~10%% of --n)",
    )
    parser.add_argument(
        "--split", choices=["val", "test"], default="test",
        help="CLINC150 split to sample from (test = held-out, recommended)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=str(REPO_ROOT / "tasks" / "clinc150.json"))
    args = parser.parse_args()

    oos_n = args.oos_n if args.oos_n is not None else max(1, round(args.n * 0.1))

    data = _fetch_json(DATA_URL)
    in_scope_rows = data[args.split]
    oos_rows = data[f"oos_{args.split}"]
    intent_labels = sorted(set(label for _, label in data["train"]))

    rng = random.Random(args.seed)
    in_scope_sample = rng.sample(in_scope_rows, min(args.n, len(in_scope_rows)))
    oos_sample = rng.sample(oos_rows, min(oos_n, len(oos_rows)))

    combined = [(text, label) for text, label in in_scope_sample] + [
        (text, OOS_LABEL) for text, _ in oos_sample
    ]
    rng.shuffle(combined)

    criteria = {label: label.replace("_", " ") for label in intent_labels}
    criteria[OOS_LABEL] = OOS_DESCRIPTION

    task = {
        "task_id": "clinc150",
        "description": (
            "CLINC150 intent classification with out-of-scope detection "
            "(Larson et al., 2019, CC BY 3.0): one Choice judgment per ticket "
            "picking the intent out of 150 categories across 10 domains, or "
            "'oos' if none apply. Sampled from the "
            f"{args.split} split, seed={args.seed}, "
            f"n={len(in_scope_sample)} in-scope + {len(oos_sample)} oos. "
            "Source: https://github.com/clinc/oos-eval"
        ),
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": (
                    "Which intent best matches this query? If it doesn't clearly "
                    "match any listed intent, answer 'oos'."
                ),
                "criteria": criteria,
            }
        },
        "tickets": [
            {
                "id": f"clinc-{i}",
                "state": text,
                "expected": {"intent": label},
            }
            for i, (text, label) in enumerate(combined)
        ],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    print(
        f"Wrote {len(in_scope_sample)} in-scope + {len(oos_sample)} oos tickets, "
        f"{len(intent_labels)} intent categories + oos -> {out_path}"
    )


if __name__ == "__main__":
    main()
