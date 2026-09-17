# typesafe-bench

Benchmarks typesafe.ai's Jev (System One model) against any set of models
deployed on Azure AI Foundry — e.g. Claude Haiku/Sonnet/Opus and GPT
Luna/Sol/Terra — on **cost** and **latency** for the same structured-decision
task.

Models are entirely config-driven: `config/models.yaml` holds one shared
Azure AI Foundry resource (endpoint + key) and a plain list of deployment
names to bench against it. Add, remove, or rename models by editing that
list — no code changes, and the file has no secrets in it so it's safe to
publish/commit as-is.

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
# fill in TYPESAFE_API_KEY, AZURE_FOUNDRY_ENDPOINT, AZURE_FOUNDRY_API_KEY
```

Then edit `config/models.yaml`:
- `models:` — one entry per deployment you want to bench, e.g.:
  ```yaml
  models:
    - name: gpt-luna       # label used in results
      deployment: gpt-luna # the actual Azure Foundry deployment name
      input_price_per_1m: null
      output_price_per_1m: null
  ```
- Fill in `input_price_per_1m` / `output_price_per_1m` for each model you
  have real pricing for (Azure Foundry pricing is plan-specific). Jev's
  input price defaults to typesafe.ai's published $42/1B tokens; its output
  price is not currently published.

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

- `results/raw_results.csv` — every individual call: latency, tokens, cached
  tokens, answers, errors, and the full raw `usage` payload the API returned
  (field names for cache/cost info differ per provider, so the raw JSON is
  kept for inspection even when the harness can't parse it)
- `results/summary.csv` — per-model mean/p50/p95 latency, avg tokens, avg
  cached tokens, avg & total cost
- Same summary printed to stdout as a table

## Prompt caching

If a provider's response reports a cached-token count (OpenAI-style
`prompt_tokens_details.cached_tokens`, Anthropic-style
`cache_read_input_tokens`, etc.), the harness picks it up automatically and
records it as `cached_input_tokens`. When `cached_input_price_per_1m` is set
for that model in `config/models.yaml`, cost for those tokens is computed at
that (typically discounted) rate instead of the standard input price.
Unrecognized usage shapes still show up in `raw_usage` in the raw CSV even
if the harness can't map them to a field.

## Notes

- Latency is wall-clock around the single API call per ticket, from this
  machine — not a server-side timing figure, so absolute latency is affected
  by your network path to each endpoint's region.
- Cost is computed as `tokens * price_per_1m` (see Prompt caching above for
  cached tokens). Any model missing a price in `config/models.yaml` reports
  cost as blank/n/a rather than 0.
- This benchmark measures cost/latency only; it does not score answer
  accuracy against ground truth.
