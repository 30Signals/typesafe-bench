from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, TextIO

import yaml
from dotenv import load_dotenv
from tabulate import tabulate

from .providers import AzureAnthropicProvider, AzureFoundryProvider, JevProvider, Provider, RunResult

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
            api_style = m.get("api_style") or _guess_api_style(m["name"], m["deployment"])
            provider_cls = AzureAnthropicProvider if api_style == "anthropic" else AzureFoundryProvider
            providers.append(
                provider_cls(
                    name=m["name"],
                    deployment=m["deployment"],
                    endpoint=endpoint,
                    api_key=api_key,
                )
            )
    return providers


def _guess_api_style(name: str, deployment: str) -> str:
    """Azure AI Foundry exposes Claude deployments only through the native
    Anthropic Messages API, not the OpenAI-style Chat Completions API every
    other model here uses -- default to that when the model looks like a
    Claude deployment. Set `api_style: anthropic` explicitly in
    config/models.yaml instead of relying on this if the name doesn't
    contain 'claude'/'anthropic'."""
    haystack = f"{name} {deployment}".lower()
    if "claude" in haystack or "anthropic" in haystack:
        return "anthropic"
    return "chat_completions"


# (input, cached_input, cache_write, output) -- USD per 1M tokens
Prices = tuple[float | None, float | None, float | None, float | None]


def price_lookup(models_config: dict[str, Any]) -> dict[str, Prices]:
    prices: dict[str, Prices] = {}
    jev_cfg = models_config["jev"]
    prices[jev_cfg["model_id"]] = (
        jev_cfg.get("input_price_per_1m"),
        jev_cfg.get("cached_input_price_per_1m"),
        jev_cfg.get("cache_write_price_per_1m"),
        jev_cfg.get("output_price_per_1m"),
    )
    for m in models_config.get("models", []):
        prices[m["name"]] = (
            m.get("input_price_per_1m"),
            m.get("cached_input_price_per_1m"),
            m.get("cache_write_price_per_1m"),
            m.get("output_price_per_1m"),
        )
    return prices


def cost_usd(
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None,
    cache_write_tokens: int | None,
    price_in: float | None,
    price_cached_in: float | None,
    price_cache_write: float | None,
    price_out: float | None,
) -> float | None:
    """`input_tokens` must already mean "new, full-price" input tokens --
    i.e. NOT including cached_input_tokens/cache_write_tokens, which are
    billed separately at their own (typically discounted for reads, premium
    for writes) rates when configured, or fall back to the standard input
    rate when not. See providers/azure_foundry.py for why this normalization
    matters: OpenAI-style APIs report a cached subset of prompt_tokens,
    while Anthropic reports cache tokens as fully separate counts -- both
    providers normalize to this same "input_tokens excludes cache" shape
    before constructing a RunResult."""
    if input_tokens is None or price_in is None:
        return None
    cost = (input_tokens / 1_000_000) * price_in
    if cached_input_tokens:
        cost += (cached_input_tokens / 1_000_000) * (
            price_cached_in if price_cached_in is not None else price_in
        )
    if cache_write_tokens:
        cost += (cache_write_tokens / 1_000_000) * (
            price_cache_write if price_cache_write is not None else price_in
        )
    if output_tokens is not None and price_out is not None:
        cost += (output_tokens / 1_000_000) * price_out
    return cost


def run_benchmark(
    providers: list[Provider],
    task: dict[str, Any],
    repeats: int,
    on_result: Callable[[RunResult], None] | None = None,
    on_provider_done: Callable[[list[RunResult]], None] | None = None,
    max_workers: int | None = None,
) -> list[RunResult]:
    """Runs one provider per worker thread, concurrently -- these are all
    I/O-bound HTTP calls to independent endpoints, so a slow model (e.g.
    kimi-k26) no longer blocks the others from progressing. Tickets within
    a single provider still run sequentially (order doesn't affect
    correctness, just keeps one model's own calls from contending with
    themselves). `on_result`/`on_provider_done` and the shared `results`
    list are only ever touched under `lock`, so callbacks (CSV writes,
    print) never interleave across threads."""
    questions = task["questions"]
    tickets = task["tickets"]
    results: list[RunResult] = []
    total = len(providers) * len(tickets) * repeats
    done = 0
    lock = threading.Lock()

    def run_provider(provider: Provider) -> None:
        nonlocal done
        for ticket in tickets:
            for _ in range(repeats):
                result = provider.run(ticket["id"], ticket["state"], questions)
                result.correct = _score_correct(result, ticket.get("expected"))
                with lock:
                    results.append(result)
                    if on_result is not None:
                        on_result(result)
                    done += 1
                    status = "ERROR" if result.error else "ok"
                    print(
                        f"[{done}/{total}] {provider.name:<16} {ticket['id']:<4} "
                        f"{result.latency_s:6.3f}s {status}"
                    )
        if on_provider_done is not None:
            with lock:
                on_provider_done(results)

    workers = max_workers or len(providers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_provider, provider) for provider in providers]
        for future in futures:
            future.result()
    return results


def _score_correct(result: RunResult, expected: dict[str, Any] | None) -> bool | None:
    """Exact-match accuracy against ground truth, if the ticket has an
    `expected` mapping of question_id -> answer (e.g. from a labeled dataset
    like BANKING77). None if there's no ground truth to check, or the call
    itself errored."""
    if not expected or result.answers is None:
        return None
    for question_id, expected_value in expected.items():
        actual = result.answers.get(question_id)
        if actual is None:
            return False
        if str(actual).strip().lower() != str(expected_value).strip().lower():
            return False
    return True


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
        price_in, price_cached_in, price_cache_write, price_out = prices.get(
            model_name, (None, None, None, None)
        )
        costs = [
            cost_usd(
                r.input_tokens, r.output_tokens, r.cached_input_tokens, r.cache_write_tokens,
                price_in, price_cached_in, price_cache_write, price_out,
            )
            for r in ok
        ]
        costs = [c for c in costs if c is not None]
        cached_counts = [r.cached_input_tokens for r in ok if r.cached_input_tokens is not None]
        cache_write_counts = [r.cache_write_tokens for r in ok if r.cache_write_tokens is not None]
        scored = [r.correct for r in ok if r.correct is not None]

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
                "avg_cache_write_tokens": round(statistics.mean(cache_write_counts), 1)
                if cache_write_counts
                else None,
                "avg_cost_usd_per_call": round(statistics.mean(costs), 6) if costs else None,
                "total_cost_usd": round(sum(costs), 6) if costs else None,
                "accuracy": round(sum(scored) / len(scored), 3) if scored else None,
            }
        )
    rows.sort(key=lambda r: (r["latency_mean_s"] is None, r["latency_mean_s"] or 0))
    return rows


RAW_CSV_FIELDS = [
    "model", "ticket_id", "latency_s", "input_tokens", "output_tokens",
    "cached_input_tokens", "cache_write_tokens", "correct", "error", "answers", "raw_usage",
]


def _raw_csv_row(r: RunResult) -> list[Any]:
    return [
        r.model_name,
        r.ticket_id,
        r.latency_s,
        r.input_tokens,
        r.output_tokens,
        r.cached_input_tokens,
        r.cache_write_tokens,
        r.correct,
        r.error or "",
        json.dumps(r.answers) if r.answers else "",
        json.dumps(r.raw_usage) if r.raw_usage else "",
    ]


class RawResultsWriter:
    """Writes raw_results.csv incrementally, flushing after every row, so a
    killed/crashed run leaves a usable partial CSV instead of losing
    everything (the harness previously only wrote results after the full
    run finished)."""

    def __init__(self, path: Path):
        self._file: TextIO = path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(RAW_CSV_FIELDS)
        self._file.flush()

    def write(self, result: RunResult) -> None:
        self._writer.writerow(_raw_csv_row(result))
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "RawResultsWriter":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


def write_raw_csv(results: list[RunResult], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(RAW_CSV_FIELDS)
        for r in results:
            writer.writerow(_raw_csv_row(r))


def write_summary_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Jev vs Azure Foundry models on cost/latency")
    parser.add_argument("--task", default=str(REPO_ROOT / "tasks" / "banking77.json"))
    parser.add_argument("--models", default=str(REPO_ROOT / "config" / "models.yaml"))
    parser.add_argument("--repeats", type=int, default=3, help="repeats per ticket per model")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "results"))
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="restrict to these provider names (e.g. jev-latest gpt-luna)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="providers to run concurrently (default: all selected providers at once)",
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

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.csv"

    with RawResultsWriter(out_dir / "raw_results.csv") as raw_writer:
        results = run_benchmark(
            providers,
            task,
            args.repeats,
            on_result=raw_writer.write,
            # Refresh summary.csv after each provider finishes so a killed
            # run still leaves usable partial results, not just raw rows.
            on_provider_done=lambda so_far: write_summary_csv(summarize(so_far, prices), summary_path),
            max_workers=args.max_workers,
        )

    rows = summarize(results, prices)
    write_summary_csv(rows, summary_path)

    print("\n=== Summary (sorted by mean latency) ===")
    print(tabulate(rows, headers="keys", tablefmt="github"))
    print(f"\nRaw results:     {out_dir / 'raw_results.csv'}")
    print(f"Summary results: {out_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
