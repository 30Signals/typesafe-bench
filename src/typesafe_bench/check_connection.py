from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .runner import REPO_ROOT, build_providers

_SMOKE_QUESTIONS = {
    "is_urgent": {
        "type": "noul",
        "instructions": "Does this convey urgency?",
    }
}
_SMOKE_STATE = "Hello, just testing connectivity. No action needed."


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One trivial call per configured model, to verify credentials/endpoints work"
    )
    parser.add_argument("--models", default=str(REPO_ROOT / "config" / "models.yaml"))
    parser.add_argument(
        "--only", nargs="*", default=None, help="restrict to these provider names"
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")

    with open(args.models, encoding="utf-8") as f:
        models_config = yaml.safe_load(f)

    providers = build_providers(models_config)
    if args.only:
        providers = [p for p in providers if p.name in args.only]
    if not providers:
        raise SystemExit("No providers selected/configured.")

    print(f"Checking {len(providers)} provider(s)...\n")
    failures = 0
    for provider in providers:
        start = time.perf_counter()
        result = provider.run("smoke", _SMOKE_STATE, _SMOKE_QUESTIONS)
        elapsed = time.perf_counter() - start
        if result.error:
            failures += 1
            print(f"[FAIL] {provider.name:<16} {elapsed:6.3f}s  {result.error}")
        else:
            print(
                f"[ OK ] {provider.name:<16} {elapsed:6.3f}s  "
                f"in={result.input_tokens} out={result.output_tokens} "
                f"cache_read={result.cached_input_tokens} cache_write={result.cache_write_tokens} "
                f"answers={json.dumps(result.answers)}"
            )

    print(f"\n{len(providers) - failures}/{len(providers)} providers OK")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
