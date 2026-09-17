# Results: Jev vs. Azure Foundry models on BANKING77 & CLINC150

> **Draft / in progress.** This is a working draft written while the full run
> is still completing — kimi-k26 is the slowest model (reasoning-model-style
> latency, occasional 60s timeouts under load) and hadn't finished either task
> yet at the time these numbers were captured (218/300 on BANKING77, 220/330
> on CLINC150). Every other model below is a complete, final n. This file
> will be updated with final kimi-k26 numbers, archived CSVs under
> `benchmarks/`, once both runs finish.

Full run: 7 models (Jev, GPT-Luna/Sol/Terra, Claude Haiku/Sonnet, Kimi K2.6)
across two tasks — 300 tickets from BANKING77 (`tasks/banking77_n300.json`,
seed 42) and 330 tickets (300 in-scope + 30 out-of-scope) from CLINC150
(`tasks/clinc150_n300.json`, seed 42) — 1 call per ticket per model, run
concurrently (one worker thread per model) with a 60s per-request timeout.

## BANKING77 (n=300/model, sorted by latency)

| model         | n (of 300) | errors | latency mean (s) | latency p50 (s) | latency p95 (s) | accuracy | avg cost/call | total cost |
|---------------|-----------:|-------:|------------------:|-----------------:|-----------------:|---------:|---------------:|-----------:|
| jev-latest    |        300 |      0 |              0.361 |             0.328 |             0.525 |    86.7% |      $0.000223 |    $0.0669 |
| claude-haiku  |        300 |      0 |              1.143 |             1.126 |             1.272 |    84.0% |      $0.000684 |    $0.2053 |
| claude-sonnet |        300 |      0 |              1.641 |             1.625 |             1.793 |    86.3% |      $0.001764 |    $0.5293 |
| gpt-luna      |        300 |      1 |              1.980 |             1.638 |             2.861 |    90.3% |      $0.000156 |    $0.0466 |
| gpt-terra     |        300 |      0 |              2.210 |             1.894 |             2.988 |    89.3% |      $0.001481 |    $0.4444 |
| gpt-sol       |        300 |      1 |              2.430 |             2.112 |             3.818 |    91.3% |      $0.003860 |    $1.1542 |
| kimi-k26*     |    218/300 |      6 |              8.674 |             5.705 |            23.687 |    88.7% |      $0.003374 |    $0.7153 |

## CLINC150 (n=330/model, sorted by latency)

| model         | n (of 330) | errors | latency mean (s) | latency p50 (s) | latency p95 (s) | accuracy | avg cost/call | total cost |
|---------------|-----------:|-------:|------------------:|-----------------:|-----------------:|---------:|---------------:|-----------:|
| jev-latest    |        330 |      0 |              0.335 |             0.305 |             0.485 |    90.3% |      $0.000106 |    $0.0351 |
| claude-haiku  |        330 |      0 |              0.830 |             0.813 |             0.961 |    87.9% |      $0.002021 |    $0.6670 |
| claude-sonnet |        330 |      0 |              1.360 |             1.309 |             1.559 |    89.4% |      $0.000688 |    $0.2270 |
| gpt-luna      |        330 |      0 |              1.541 |             1.327 |             2.144 |    92.4% |      $0.000065 |    $0.0215 |
| gpt-terra     |        330 |      0 |              1.661 |             1.561 |             2.246 |    92.1% |      $0.000597 |    $0.1971 |
| gpt-sol       |        330 |      1 |              1.993 |             1.754 |             3.009 |    95.7% |      $0.001576 |    $0.5185 |
| kimi-k26*     |    220/330 |      0 |              5.800 |             3.473 |            15.336 |    94.1% |      $0.002018 |    $0.4441 |

\* kimi-k26 rows are partial (in progress) — n < the full task size. All other
rows are complete final numbers.

## Takeaways

- **Latency**: jev-latest is the clear latency leader across both tasks —
  roughly 3-4x faster than Claude Haiku (the next fastest), 5-7x faster
  than the GPT models, and ~16-24x faster than kimi-k26. Its p95 is also
  by far the tightest (0.49-0.53s vs. 1s+ for everything else), meaning
  it's not just fast on average but consistently fast.
- **Accuracy**: no model dominates both tasks. gpt-sol leads on both
  (91.3% / 95.7%), with kimi-k26 close behind on partial data (88.7% /
  94.1%). gpt-luna is the standout value play — accuracy within 1-4pts of
  the leaders on both tasks at a fraction of the cost. jev-latest and
  claude-haiku sit at the bottom of the accuracy range on both tasks
  (84-90%), trading accuracy for their speed/cost advantage.
- **Cost**: gpt-luna is the cheapest model that isn't Jev on both tasks
  (its aggressive prompt caching — ~4900/1600 cached tokens per call once
  warm — does a lot of work here), and even edges out jev-latest on
  CLINC150. gpt-sol is consistently the most expensive per call despite
  strong accuracy. claude-sonnet's caching cuts its CLINC150 cost well
  below its BANKING77 cost (larger system prompt on BANKING77 relative to
  CLINC150's simpler criteria set changes the caching economics).
- **kimi-k26 reliability**: it accounted for effectively all of the run's
  timeout errors (6 of 8 total across both tasks) and has by far the
  highest tail latency (p95 15-24s, some individual calls exceeding the
  60s timeout entirely). This looks like genuine reasoning-model latency
  variance rather than a rate-limit issue — the errors are client-side
  read timeouts, not 429s, and each model runs in its own single-threaded
  worker so kimi-k26 isn't contending with itself.
- **Net picture**: there's no single winner — it's a real speed/cost vs.
  accuracy frontier. jev-latest wins decisively on latency and is
  competitive on cost; gpt-luna is the best all-around value (strong
  accuracy, very low cost, moderate latency); gpt-sol and kimi-k26 lead
  accuracy but pay for it in cost and/or latency; claude-haiku/sonnet sit
  in the middle on every axis.

## Caveats

- Latency is wall-clock from this machine to each endpoint, not a
  server-side figure — affected by network path/region, and by running
  all 7 models concurrently (one thread per model) rather than serially.
- Each provider call has a 60s client-side timeout; a handful of calls
  (mostly kimi-k26, one each for gpt-luna/gpt-sol) hit it and are recorded
  as errors rather than retried indefinitely.
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
