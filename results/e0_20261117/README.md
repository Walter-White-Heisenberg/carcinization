# Completed E0 development results

One fixed development manuscript (Attention Is All You Need, arXiv v1), three shared starting reviews, two update conditions and two updates. All 15 planned generations and their automatic structural annotations completed. This is a development observation, not the six-paper pilot.

| Round | D recursive | D independent | C recursive | C independent | Extra contraction |
|---|---:|---:|---:|---:|---:|
| 0 | 0.477535 | 0.477535 | 0.000000 | 0.000000 | 0.000000 |
| 1 | 0.320364 | 0.353959 | 0.157171 | 0.123576 | 0.033595 |
| 2 | 0.310458 | 0.355112 | 0.167078 | 0.122423 | 0.044654 |

Distances use the mean of the three normalized edit distances between functional-role sequences. Shared seeds are counted once. The recursive condition contracted more in this run; one paper and two updates cannot establish a persistent or general convergence effect.

The separate quality check was a posthoc, nonblind source audit by one AI system, with no independent human adjudication. Valid-concern retention was 52/52 and 58/59 for recursive updates, versus 47/52 and 45/59 for independent updates. Repeated concerns and trajectories are correlated observations of a single paper. Retention alone is not overall review quality. Known-issue recall was unavailable because no pre-generation gold denominator existed; invalid-concern persistence was unavailable because its eligible denominator was zero. These missing values are not zero effects.

The manuscript never changed, so no article-quality improvement or deterioration is measured. Structural similarity and scientific validity are separate outcomes.

Run `python scripts/verify_published_results.py` to recompute all published structural distances from the included label sequences. This verifies arithmetic and file binding; it does not independently validate the labels or the quality judgments. The request/response archive and source-annotation evidence are not included in this bounded public export.
