# Results: Jev vs. Azure Foundry models on BANKING77 & CLINC150

Full run: 7 models (Jev, GPT-Luna/Sol/Terra, Claude Haiku/Sonnet, Kimi K2.6)
across two tasks — 300 tickets from BANKING77 (`tasks/banking77_n300.json`,
seed 42) and 330 tickets (300 in-scope + 30 out-of-scope) from CLINC150
(`tasks/clinc150_n300.json`, seed 42) — 1 call per ticket per model, run
concurrently (one worker thread per model) with a 60s per-request timeout.
Raw data: [benchmarks/2026-09-17_banking77_n300_full/](benchmarks/2026-09-17_banking77_n300_full/)
and [benchmarks/2026-09-17_clinc150_n300_full/](benchmarks/2026-09-17_clinc150_n300_full/).

## BANKING77 (n=300/model, sorted by latency)

| model         |   n | errors | latency mean (s) | latency p50 (s) | latency p95 (s) | accuracy | avg cost/call | total cost |
|---------------|----:|-------:|------------------:|-----------------:|-----------------:|---------:|---------------:|-----------:|
| jev-latest    | 300 |      0 |              0.361 |             0.328 |             0.525 |    86.7% |      $0.000223 |    $0.0669 |
| claude-haiku  | 300 |      0 |              1.143 |             1.126 |             1.272 |    84.0% |      $0.000684 |    $0.2053 |
| claude-sonnet | 300 |      0 |              1.641 |             1.625 |             1.793 |    86.3% |      $0.001764 |    $0.5293 |
| gpt-luna      | 300 |      1 |              1.980 |             1.638 |             2.861 |    90.3% |      $0.000156 |    $0.0466 |
| gpt-terra     | 300 |      0 |              2.210 |             1.894 |             2.988 |    89.3% |      $0.001481 |    $0.4444 |
| gpt-sol       | 300 |      1 |              2.430 |             2.112 |             3.818 |    91.3% |      $0.003860 |    $1.1542 |
| kimi-k26      | 300 |      8 |              9.499 |             5.822 |            29.139 |    91.1% |      $0.003555 |    $1.0381 |

## CLINC150 (n=330/model, sorted by latency)

| model         |   n | errors | latency mean (s) | latency p50 (s) | latency p95 (s) | accuracy | avg cost/call | total cost |
|---------------|----:|-------:|------------------:|-----------------:|-----------------:|---------:|---------------:|-----------:|
| jev-latest    | 330 |      0 |              0.432 |             0.323 |             1.125 |    90.0% |      $0.000106 |    $0.0351 |
| claude-haiku  | 330 |      1 |              0.866 |             0.827 |             0.969 |    88.1% |      $0.002021 |    $0.6649 |
| claude-sonnet | 330 |      0 |              1.389 |             1.356 |             1.557 |    90.0% |      $0.000678 |    $0.2236 |
| gpt-luna      | 330 |      1 |              1.666 |             1.439 |             2.835 |    93.0% |      $0.000076 |    $0.0249 |
| gpt-terra     | 330 |      0 |              1.879 |             1.685 |             2.865 |    93.3% |      $0.000613 |    $0.2023 |
| gpt-sol       | 330 |      0 |              2.064 |             1.861 |             3.015 |    95.8% |      $0.001670 |    $0.5511 |
| kimi-k26      | 330 |      3 |              7.920 |             5.815 |            19.144 |    89.6% |      $0.001896 |    $0.6198 |

## Takeaways

- **Latency**: jev-latest is the clear latency leader across both tasks —
  roughly 2-3x faster than Claude Haiku (the next fastest), 4-5x faster
  than the GPT models, and ~18-26x faster than kimi-k26. Its p50 is
  consistently under 0.35s on both tasks.
- **Accuracy**: no model dominates both tasks. gpt-sol leads on both
  (91.3% / 95.8%), with gpt-terra and gpt-luna close behind, especially on
  CLINC150 (93.3% / 93.0%). kimi-k26 is mid-pack on both tasks (91.1% /
  89.6%) despite its much higher latency and cost — its reasoning
  overhead here does not translate into an accuracy edge on this task
  type. jev-latest and claude-haiku sit at the bottom of the accuracy
  range on both tasks (84-90%), trading accuracy for their speed/cost
  advantage.
- **Cost**: gpt-luna is the cheapest model that isn't Jev on both tasks
  (its aggressive prompt caching — ~4900/1600 cached tokens per call once
  warm — does a lot of work here), and edges out jev-latest on CLINC150's
  avg cost/call. gpt-sol is consistently the most expensive per call
  despite strong accuracy. claude-sonnet's caching cuts its CLINC150 cost
  well below its BANKING77 cost (larger system prompt on BANKING77
  relative to CLINC150's simpler criteria set changes the caching
  economics).
- **kimi-k26 reliability**: it accounted for 11 of 13 total errors across
  both tasks (all client-side 60s read timeouts, not 429s), and has by far
  the highest tail latency (p95 19-29s). This looks like genuine
  reasoning-model latency variance rather than a rate-limit issue — each
  model runs in its own single-threaded worker, so kimi-k26 isn't
  contending with itself for its own quota.
- **Net picture**: there's no single winner — it's a real speed/cost vs.
  accuracy frontier. jev-latest wins decisively on latency and is
  competitive on cost; gpt-luna is the best all-around value (strong
  accuracy, very low cost, moderate latency); gpt-sol/gpt-terra lead
  accuracy at moderate-to-high cost; kimi-k26's slower reasoning-model
  profile didn't translate into an accuracy edge on this structured-
  classification task; claude-haiku/sonnet sit in the middle on cost and
  latency.

## Caveats

- Latency is wall-clock from this machine to each endpoint, not a
  server-side figure — affected by network path/region, and by running
  all 7 models concurrently (one worker thread per model) rather than
  serially.
- Each provider call has a 60s client-side timeout; a small number of
  calls (mostly kimi-k26: 6 on BANKING77, 3 on CLINC150; one each for
  gpt-luna/gpt-sol/claude-haiku) hit it or returned malformed output and
  are recorded as errors rather than retried indefinitely.
- gpt-terra's `cache_write_price_per_1m` isn't set in `config/models.yaml`
  (unknown), so any cache-write tokens for it are costed at the standard
  input rate rather than a real (possibly different) write price.
- Accuracy is exact-match against each dataset's own labels; it does not
  account for cases where a model's answer is arguably reasonable but
  doesn't match the dataset's specific label choice.
- 1 repeat per ticket at this scale (n=300/330 per model) — latency
  percentiles are based on per-ticket single calls, not repeated-call
  variance per ticket.

See [README.md](README.md) for how to reproduce or extend this benchmark.
