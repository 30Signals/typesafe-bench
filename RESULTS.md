# Results: Jev vs. Azure Foundry models on BANKING77

Latest full run: 300 tickets sampled from BANKING77 (`tasks/banking77_n300.json`,
seed 42), 1 call per ticket per model, criteria enriched with real example
queries per category (see [scripts/build_banking77_task.py](scripts/build_banking77_task.py)).
Raw data: [benchmarks/2026-09-17_banking77_n300/](benchmarks/2026-09-17_banking77_n300/).

| model      | n   | errors | latency mean (s) | latency p50 (s) | latency p95 (s) | accuracy | avg cost/call | total cost |
|------------|----:|-------:|------------------:|-----------------:|-----------------:|---------:|---------------:|-----------:|
| jev-latest | 300 |      0 |              0.473 |             0.420 |             0.509 |    87.3% |      $0.000223 |   $0.06695 |
| gpt-luna   | 300 |      0 |              2.320 |             1.529 |             3.272 |    91.3% |      $0.000156 |   $0.04688 |
| gpt-terra  | 300 |      0 |              2.218 |             1.740 |             2.947 |    89.7% |      $0.001618 |   $0.48547 |

## Takeaways

- **Latency**: Jev is ~4.7x faster than either GPT model on mean latency,
  with a much tighter p95 (0.51s vs. 2.9-3.3s). This is Jev's clearest,
  most consistent advantage in this benchmark.
- **Accuracy**: closer than it first looked. An earlier pass with bare
  category-name criteria (no example queries) showed Jev at 79.3% vs.
  87.0% for both GPT models — a ~7.7pt gap. Adding 2-3 real example
  queries per category (applied identically to every model) narrowed that
  to 87.3% vs. 91.3%/89.7% — a ~4pt gap. Several BANKING77 categories are
  genuinely close synonyms (e.g. `order_physical_card` vs.
  `get_physical_card`, `beneficiary_not_allowed` vs. `failed_transfer`/
  `declined_transfer`) that a bare label name doesn't disambiguate for any
  model, but Jev was more sensitive to that under-specification than the
  GPT models were.
- **Cost**: gpt-luna's aggressive prompt caching (avg ~4870 cached tokens
  per call once warm) makes it the cheapest of the three overall, edging
  out Jev. gpt-terra is by far the most expensive — its per-token rates
  are much higher, and caching doesn't close that gap.
- Net picture: Jev wins clearly on latency, is competitive but behind on
  accuracy, and sits in the middle on cost (beats gpt-terra, doesn't quite
  match gpt-luna's cached cost).

## Caveats

- Latency is wall-clock from this machine to each endpoint, not a
  server-side figure — affected by network path/region.
- gpt-terra's `cache_write_price_per_1m` isn't set in `config/models.yaml`
  (unknown), so any cache-write tokens for it are costed at the standard
  input rate rather than a real (possibly different) write price — worth
  filling in if that rate is known, as it could shift its total cost.
- Accuracy is exact-match against BANKING77's own labels; it does not
  account for cases where a model's answer is arguably reasonable but
  doesn't match the dataset's specific label choice.
- 1 repeat per ticket at this scale (n=300) — latency percentiles are
  based on per-ticket single calls, not repeated-call variance per ticket.

See [README.md](README.md) for how to reproduce or extend this benchmark.
