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

Default: `tasks/banking77.json` — a sample of the
[BANKING77](https://github.com/PolyAI-LDN/task-specific-datasets) intent
classification dataset (Casanueva et al., 2020, CC BY 4.0). One Choice
judgment per ticket, picking the customer's intent out of 77 real banking
categories, over real customer queries. Each ticket carries a ground-truth
`expected` label, so results include an `accuracy` column alongside cost and
latency — not just cost/latency as before. Regenerate or resample it with:

```bash
python scripts/build_banking77_task.py --n 30 --seed 42
```

Options: `--n` (ticket count), `--split train|test`, `--seed`, `--out`.

Also included:

- `tasks/clinc150.json` — a sample of [CLINC150](https://github.com/clinc/oos-eval)
  (Larson et al., 2019, CC BY 3.0): 150 intents across 10 broad domains
  (banking, travel, utility, work, small talk, etc.) *plus* an explicit
  out-of-scope ("oos") class for queries that don't match any listed intent.
  Ground truth included, same as BANKING77. Where BANKING77 tests "pick the
  right label," this also tests "recognize when no label fits" — directly
  relevant to Jev's calibrated-decision pitch. Regenerate/resample with:
  ```bash
  python scripts/build_clinc150_task.py --n 30 --oos-n 3 --seed 42
  ```
  Options: `--n` (in-scope tickets), `--oos-n` (out-of-scope tickets,
  default ~10% of `--n`), `--split val|test`, `--seed`, `--out`. Use with
  `--task tasks/clinc150.json`.
- `tasks/ticket_triage.json` — a synthetic support-ticket task asking three
  judgments at once (a Noul, a Choice, and a Score) per ticket, matching
  typesafe.ai's own worked example. No ground truth (cost/latency only) but
  exercises multiple question types in one call, unlike BANKING77/CLINC150's
  single Choice question. Use it with `--task tasks/ticket_triage.json`.

Every model is asked the same question(s) over the same ticket text via one
JSON structured-output call, for an apples-to-apples per-request comparison.

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

- `results/raw_results.csv` — every individual call: latency, tokens, cache
  read/write tokens, whether the answer matched ground truth (`correct`,
  blank if the task has no `expected` for that ticket), answers, errors, and
  the full raw `usage` payload the API returned (field names for cache/cost
  info differ per provider, so the raw JSON is kept for inspection even when
  the harness can't parse it)
- `results/summary.csv` — per-model mean/p50/p95 latency, avg tokens, avg
  cache read/write tokens, avg & total cost, and `accuracy` (blank if the
  task has no ground truth)
- Same summary printed to stdout as a table

## Prompt caching

Every prompt is built so the static instructions + question definitions
(identical on every call for a given task) form the system message/prompt —
a stable prefix — and only the ticket text varies. This ordering is required
for prefix-based caching to have any chance of working at all.

If a provider's response reports a cached-token count, the harness picks it
up (provider-agnostic field detection: OpenAI-style
`prompt_tokens_details.cached_tokens`, Anthropic-style
`cache_read_input_tokens`/`cache_creation_input_tokens`, etc.) and records
it as `cached_input_tokens` (cache reads) and `cache_write_tokens` (cache
writes, Anthropic-only). Unrecognized usage shapes still show up in
`raw_usage` in the raw CSV even when the harness can't map them to a field.

**Token accounting is normalized across providers before cost is computed.**
OpenAI-style APIs report `prompt_tokens` as a total that *includes* the
cached subset; Anthropic reports cache read/write tokens as fully separate
counts alongside a smaller `input_tokens`. Both providers convert to the
same shape before building a result: `input_tokens` always means "new,
full-price" tokens, with `cached_input_tokens`/`cache_write_tokens` billed
on top at their own rates (`cached_input_price_per_1m`,
`cache_write_price_per_1m`) when configured, falling back to the standard
input rate otherwise. Mixing up these two accounting styles would silently
under- or over-count cost for whichever provider used the other convention.

**Claude is opt-in, not automatic.** Unlike OpenAI-style models (which
auto-cache long repeated prefixes with no extra request fields), Azure
Foundry's Claude deployments only speak the native Anthropic Messages API
(`<endpoint>/anthropic` — routed automatically via `api_style: anthropic`
in `config/models.yaml`) and require an explicit `cache_control: ephemeral`
breakpoint on the prefix to write it to cache at all — this harness sets
that breakpoint on the system prompt for every Claude call.

**Minimum cacheable length still applies.** Anthropic won't cache a prefix
shorter than ~1024 tokens (Sonnet/Opus) or ~2048 tokens (Haiku), regardless
of `cache_control`. `tasks/ticket_triage.json`'s system prompt is only
~350-400 tokens, so on that task Claude's `cache_write_tokens` will
legitimately stay 0 — that's expected, not a bug. `tasks/banking77.json`'s
77-option Choice criteria push the system prompt well past that floor, so
caching (and OpenAI's automatic caching, which has its own ~1024-token
minimum) actually engages on that task.

## Notes

- Latency is wall-clock around the single API call per ticket, from this
  machine — not a server-side timing figure, so absolute latency is affected
  by your network path to each endpoint's region.
- Cost is computed as `tokens * price_per_1m` (see Prompt caching above for
  the cache read/write accounting). Any model missing a price in
  `config/models.yaml` reports cost as blank/n/a rather than 0.
- Accuracy is only reported for tasks whose tickets carry an `expected`
  ground-truth mapping (e.g. `tasks/banking77.json`); it's an exact,
  case-insensitive string match on the answer, not partial credit.
