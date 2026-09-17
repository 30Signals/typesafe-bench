from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from tabulate import tabulate

from .providers import AzureFoundryProvider, JevProvider, Provider, RunResult

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_providers(models_config: dict[str, Any]) -> list[Provider]:
    providers: list[Provider] = []

    jev_cfg = models_config["jev"]
    providers.append(
        JevProvider(
            name=jev_cfg["model_id"],
            model_id=jev_cfg["model_id"],
            api_key_env=jev_cfg["api_key_env"],
        )
    )

    azure_models = models_config.get("models", [])
    if azure_models:
        azure_cfg = models_config["azure"]
        endpoint = os.environ.get(azure_cfg["endpoint_env"])
        api_key = os.environ.get(azure_cfg["api_key_env"])
        if not endpoint or not api_key:
            raise RuntimeError(
                f"Missing {azure_cfg['endpoint_env']} and/or {azure_cfg['api_key_env']} "
                "for the shared Azure AI Foundry resource"
            )
        for m in azure_models:
            providers.append(
                AzureFoundryProvider(
                    name=m["name"],
                    deployment=m["deployment"],
                    endpoint=endpoint,
                    api_key=api_key,
                )
            )
    return providers


Prices = tuple[float | None, float | None, float | None]  # (input, cached_input, output)


def price_lookup(models_config: dict[str, Any]) -> dict[str, Prices]:
    prices: dict[str, Prices] = {}
    jev_cfg = models_config["jev"]
    prices[jev_cfg["model_id"]] = (
        jev_cfg.get("input_price_per_1m"),
        jev_cfg.get("cached_input_price_per_1m"),
        jev_cfg.get("output_price_per_1m"),
    )
    for m in models_config.get("models", []):
        prices[m["name"]] = (
            m.get("input_price_per_1m"),
            m.get("cached_input_price_per_1m"),
            m.get("output_price_per_1m"),
        )
    return prices


def cost_usd(
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None,
    price_in: float | None,
    price_cached_in: float | None,
    price_out: float | None,
) -> float | None:
    """Cached input tokens are billed at `price_cached_in` (typically a
    discounted rate) instead of `price_in` when both the token count and
    that price are known; otherwise all input tokens fall back to the
    standard input price."""
    if input_tokens is None or price_in is None:
        return None
    cached = cached_input_tokens or 0
    if cached and price_cached_in is not None:
        uncached = max(input_tokens - cached, 0)
        cost = (uncached / 1_000_000) * price_in + (cached / 1_000_000) * price_cached_in
    else:
        cost = (input_tokens / 1_000_000) * price_in
    if output_tokens is not None and price_out is not None:
        cost += (output_tokens / 1_000_000) * price_out
    return cost


def run_benchmark(
    providers: list[Provider],
    task: dict[str, Any],
    repeats: int,
) -> list[RunResult]:
    questions = task["questions"]
    tickets = task["tickets"]
    results: list[RunResult] = []
    total = len(providers) * len(tickets) * repeats
    done = 0
    for provider in providers:
        for ticket in tickets:
            for _ in range(repeats):
                result = provider.run(ticket["id"], ticket["state"], questions)
                results.append(result)
                done += 1
                status = "ERROR" if result.error else "ok"
                print(
                    f"[{done}/{total}] {provider.name:<16} {ticket['id']:<4} "
                    f"{result.latency_s:6.3f}s {status}"
                )
    return results


def summarize(
    results: list[RunResult], prices: dict[str, Prices]
) -> list[dict[str, Any]]:
    by_model: dict[str, list[RunResult]] = {}
    for r in results:
        by_model.setdefault(r.model_name, []).append(r)

    rows = []
    for model_name, rs in by_model.items():
        ok = [r for r in rs if r.error is None]
        errors = len(rs) - len(ok)
        latencies = sorted(r.latency_s for r in ok) if ok else []
        price_in, price_cached_in, price_out = prices.get(model_name, (None, None, None))
        costs = [
            cost_usd(
                r.input_tokens, r.output_tokens, r.cached_input_tokens,
                price_in, price_cached_in, price_out,
            )
            for r in ok
        ]
        costs = [c for c in costs if c is not None]
        cached_counts = [r.cached_input_tokens for r in ok if r.cached_input_tokens is not None]

        def pct(data: list[float], p: float) -> float | None:
            if not data:
                return None
            k = int(round(p * (len(data) - 1)))
            return data[k]

        rows.append(
            {
                "model": model_name,
                "n": len(rs),
                "errors": errors,
                "latency_mean_s": round(statistics.mean(latencies), 3) if latencies else None,
                "latency_p50_s": round(pct(latencies, 0.5), 3) if latencies else None,
                "latency_p95_s": round(pct(latencies, 0.95), 3) if latencies else None,
                "avg_input_tokens": round(
                    statistics.mean([r.input_tokens for r in ok if r.input_tokens is not None]), 1
                )
                if any(r.input_tokens is not None for r in ok)
                else None,
                "avg_output_tokens": round(
                    statistics.mean([r.output_tokens for r in ok if r.output_tokens is not None]), 1
                )
                if any(r.output_tokens is not None for r in ok)
                else None,
                "avg_cached_input_tokens": round(statistics.mean(cached_counts), 1)
                if cached_counts
                else None,
                "avg_cost_usd_per_call": round(statistics.mean(costs), 6) if costs else None,
                "total_cost_usd": round(sum(costs), 6) if costs else None,
            }
        )
    rows.sort(key=lambda r: (r["latency_mean_s"] is None, r["latency_mean_s"] or 0))
    return rows


def write_raw_csv(results: list[RunResult], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "model", "ticket_id", "latency_s", "input_tokens", "output_tokens",
                "cached_input_tokens", "error", "answers", "raw_usage",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.model_name,
                    r.ticket_id,
                    r.latency_s,
                    r.input_tokens,
                    r.output_tokens,
                    r.cached_input_tokens,
                    r.error or "",
                    json.dumps(r.answers) if r.answers else "",
                    json.dumps(r.raw_usage) if r.raw_usage else "",
                ]
            )


def write_summary_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Jev vs Azure Foundry models on cost/latency")
    parser.add_argument("--task", default=str(REPO_ROOT / "tasks" / "ticket_triage.json"))
    parser.add_argument("--models", default=str(REPO_ROOT / "config" / "models.yaml"))
    parser.add_argument("--repeats", type=int, default=3, help="repeats per ticket per model")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "results"))
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="restrict to these provider names (e.g. jev-latest gpt-luna)",
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")

    with open(args.models, encoding="utf-8") as f:
        models_config = yaml.safe_load(f)
    with open(args.task, encoding="utf-8") as f:
        task = json.load(f)

    providers = build_providers(models_config)
    if args.only:
        providers = [p for p in providers if p.name in args.only]
    if not providers:
        raise SystemExit("No providers selected/configured.")

    prices = price_lookup(models_config)

    results = run_benchmark(providers, task, args.repeats)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_raw_csv(results, out_dir / "raw_results.csv")

    rows = summarize(results, prices)
    write_summary_csv(rows, out_dir / "summary.csv")

    print("\n=== Summary (sorted by mean latency) ===")
    print(tabulate(rows, headers="keys", tablefmt="github"))
    print(f"\nRaw results:     {out_dir / 'raw_results.csv'}")
    print(f"Summary results: {out_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
