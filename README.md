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

    - name: claude-sonnet
      deployment: claude-sonnet-5
      api_style: anthropic  # Claude on Foundry needs the native Anthropic API, not chat_completions
      input_price_per_1m: null
      output_price_per_1m: null
  ```
- Fill in `input_price_per_1m` / `output_price_per_1m` for each model you
  have real pricing for (Azure Foundry pricing is plan-specific). Jev's
  input price defaults to typesafe.ai's published $42/1B tokens; its output
  price is not currently published.

## Verify setup

Before a full run, sanity-check that every configured model is reachable
with one trivial call each:

```bash
python check_connection.py
```

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

Every prompt is built so the static instructions + question definitions
(identical on every call for a given task) form the system message/prompt —
a stable prefix — and only the ticket text varies. This ordering is required
for prefix-based caching to have any chance of working at all.

If a provider's response reports a cached-token count, the harness picks it
up (provider-agnostic field detection: OpenAI-style
`prompt_tokens_details.cached_tokens`, Anthropic-style
`cache_read_input_tokens`, etc.) and records it as `cached_input_tokens`
(cache reads) and `cache_write_tokens` (cache writes, Anthropic-only).
Unrecognized usage shapes still show up in `raw_usage` in the raw CSV even
when the harness can't map them to a field. When `cached_input_price_per_1m`
is set for a model, cost for cache-read tokens is computed at that
(discounted) rate instead of the standard input price.

**Claude is opt-in, not automatic.** Unlike OpenAI-style models (which
auto-cache long repeated prefixes with no extra request fields), Azure
Foundry's Claude deployments only speak the native Anthropic Messages API
(`<endpoint>/anthropic` — routed automatically via `api_style: anthropic`
in `config/models.yaml`) and require an explicit `cache_control: ephemeral`
breakpoint on the prefix to write it to cache at all — this harness sets
that breakpoint on the system prompt for every Claude call.

**Minimum cacheable length still applies.** Anthropic won't cache a prefix
shorter than ~1024 tokens (Sonnet/Opus) or ~2048 tokens (Haiku), regardless
of `cache_control`. The bundled `tasks/ticket_triage.json` system prompt is
only ~350-400 tokens, so on this task Claude's `cache_write_tokens` will
legitimately stay 0 — that's expected, not a bug. To actually exercise
caching on Claude, the static shared content would need to grow past that
floor (more policy text, examples, question definitions, etc.).

## Notes

- Latency is wall-clock around the single API call per ticket, from this
  machine — not a server-side timing figure, so absolute latency is affected
  by your network path to each endpoint's region.
- Cost is computed as `tokens * price_per_1m` (see Prompt caching above for
  cached tokens). Any model missing a price in `config/models.yaml` reports
  cost as blank/n/a rather than 0.
- This benchmark measures cost/latency only; it does not score answer
  accuracy against ground truth.
