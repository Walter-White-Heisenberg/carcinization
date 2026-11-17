# Carcinization

Experiments on structural convergence in iterative peer review.

This project studies whether repeated reviews of a fixed manuscript become more similar, and how structural changes relate to the validity and retention of scientific concerns. It compares reviews that receive the previous review with independently generated reviews that receive only the manuscript.

## Status

The E0 development experiment has completed 15 generation slots on one manuscript. Its measurements are exploratory. The six-paper pilot is being prepared and has **not** been run. No pilot results, significance claims, or verified training-data exclusion are reported.

## Design

- Three independently generated starting reviews per manuscript, shared between the two conditions.
- Ten fixed updates in each condition. The recursive condition receives the fixed manuscript and only its own preceding review; the independent condition receives the manuscript without prior reviews.
- 63 planned generations per paper; 378 across six papers, before evaluation or retries.
- Functional-role sequence distance, within-condition contraction, and additional contraction relative to the independent condition.
- Separate review-content assessments: concern validity, known-issue recall where a pre-generation evidence set exists, valid-concern retention, and invalid-concern persistence where the denominator exists.
- Missing, disputed, and unassessable judgments stay visible. Structural similarity is not treated as evidence of scientific deterioration.

## Selected papers

The recent papers were selected because their arXiv v1 dates are after 2026-04-30. Their latest versions were checked and pinned on 2026-11-18. The older and recent papers are matched by broad topic, not by all methodological or publication characteristics.

| Older paper | Recent paper | Recent v1 date (UTC) | Pinned latest version |
|---|---|---|---|
| A Closer Look at Few-shot Classification (ICLR 2019) | [Decompose, Compare, and Decide: Multimodal LLMs are Implicit Few-Shot Learners](https://arxiv.org/abs/2607.00125) | 2026-06-30 | v1 |
| How Does Mixup Help With Robustness and Generalization? (ICLR 2021) | [$S^{2}$-FracMix: Label-Preserving Self-Saliency Mixup Augmentation](https://arxiv.org/abs/2606.25784) | 2026-06-24 | v1 |
| Implementation Matters in Deep RL: A Case Study on PPO and TRPO (ICLR 2020) | [Where Entropy Is Measured Matters: Policy Geometry in Bounded Continuous-Control PPO](https://arxiv.org/abs/2608.24488) | 2026-08-25 | v1 |

See [the paper manifest](data/paper_selection.json) for exact version URLs, source-check timestamps, histories, and PDF hashes. PDFs are referenced rather than redistributed. The older papers' exact manuscript versions remain to be locked before generation.

Publication after a reported knowledge cutoff reduces one source of possible training exposure; it does **not** establish that the paper was excluded from training. Older papers are not assumed to have been included. This is a purposive exploratory sample, not a randomized estimate of a training-contamination effect.

## Local checks

The current E0 coordinator uses Windows file locking and requires Python 3.12 on Windows.

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s experiment/tests -v
```

The tests use simulated provider responses and do not need API credentials or make paid model calls. Fixture outputs are engineering checks, not research observations. Individual metric utilities can be used separately from the Windows coordinator.

## Running experiments

Read [the development guide](docs/DEVELOPMENT_E0_CN.md) and [the staged experiment plan](docs/MINIMAL_EXPLORATION_PLAN.md). Provider credentials, exact models, sampling settings, a dated price check, and an explicit total budget must be configured locally before any live call. The shipped pilot configuration is inactive.

The included recovery modules preserve attempt-level provenance and conservative reservations for responses whose upstream outcome is unknown. Provider endpoints must be explicitly configured; using a default endpoint with a credential intended for another provider is not supported. Formal pilot execution and its evidence requirements are separate from the E0 development coordinator.

## Repository contents

- `experiment/src/`: generation coordination, provenance, validation, and metric utilities.
- `experiment/prompts/` and `experiment/schemas/`: task templates and record contracts.
- `experiment/tests/`: offline transport, budget, recovery, and coordinator checks.
- `data/`: selected-paper metadata and version records.
- `docs/`: methods, evidence limits, and development instructions.

This repository is a portable source export. Local credentials, account configuration, personal filesystem paths, private annotations, raw provider responses, and third-party source archives are excluded. Historical run snapshots remain in the research workspace; this export is not represented as a byte-identical archive of those snapshots.

## Development results and next run

[Completed E0 results](results/e0_20261117/README.md) now include the automatic label sequences, all three rounds of structural metrics, a bounded posthoc quality summary, provenance hashes, and an offline arithmetic verifier.

The independent [E1 ten-update entry](docs/DEVELOPMENT_E1_CN.md) is prepared and offline-tested. It has not made paid calls. E1 requires a new cumulative budget instruction; it does not reuse E0 reviews. The six-paper batch remains unexecuted, and the three recent papers still have no guaranteed training exclusion.
