# typesafe-bench

Benchmarks typesafe.ai's Jev (System One model) against Claude Haiku/Sonnet/Opus
and GPT Luna/Sol/Terra — all six deployed on Azure AI Foundry — on **cost** and
**latency** for the same structured-decision task.

## Task

`tasks/ticket_triage.json` defines a support-ticket triage task: one Jev-style
call per ticket asking three questions at once (a Noul, a Choice, and a Score),
matching typesafe.ai's own worked example so Jev runs on a task it's designed for.
Every other model is asked the same three questions over the same ticket text via
one JSON structured-output call, for an apples-to-apples per-request comparison.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in TYPESAFE_API_KEY and, for each Azure Foundry model, its
# dedicated ENDPOINT / KEY / DEPLOYMENT env vars
```

Fill in `input_price_per_1m` / `output_price_per_1m` in `config/models.yaml`
for each model you have real pricing for (Azure Foundry pricing is
plan-specific). Jev's input price defaults to typesafe.ai's published
$42/1B tokens; its output price is not currently published.

## Run

```bash
python bench.py --repeats 3
```

Options:
- `--repeats N` — calls per ticket per model (default 3), for stable latency stats
- `--only jev-latest gpt-luna` — restrict to specific provider names
- `--task path/to/task.json` — use a different task file
- `--out-dir results/` — where raw_results.csv / summary.csv are written

## Output

- `results/raw_results.csv` — every individual call: latency, tokens, answers, errors
- `results/summary.csv` — per-model mean/p50/p95 latency, avg tokens, avg & total cost
- Same summary printed to stdout as a table

## Notes

- Latency is wall-clock around the single API call per ticket, from this
  machine — not a server-side timing figure, so absolute latency is affected
  by your network path to each endpoint's region.
- Cost is computed as `tokens * price_per_1m`. Any model missing a price in
  `config/models.yaml` reports cost as blank/n/a rather than 0.
- This benchmark measures cost/latency only; it does not score answer
  accuracy against ground truth.
