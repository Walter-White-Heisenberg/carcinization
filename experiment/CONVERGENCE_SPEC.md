# Methods and interpretation

Track A holds each manuscript fixed and compares recursive and independent review protocols. Every generation starts a new model session. The only history available to the recursive protocol is that trajectory's immediate previous complete review. Conditions do not exchange reviews. Model calls are interleaved according to an order fixed before viewing their outputs.

Three starting reviews are generated without selecting for structural diversity. Shared starting reviews have one identity and are counted once. Each paper has 3 + 3 × 2 × 10 = 63 planned generation slots. Round count is fixed before generation; results do not determine when a trajectory stops.

The primary structural representation consists of functional labels for body blocks, excluding headings. Adjacent identical labels are retained. Pairwise edit distance is divided by the longer sequence length and averaged over the three trajectory pairs. D(t) measures within-condition diversity; C(t)=D(0)-D(t); additional contraction is C_recursive(t)-C_independent(t). The manuscript, rather than each review or concern occurrence, is the experimental unit.

Content assessment distinguishes valid, invalid, uncertain, and disputed concerns. Concern identity is based on target, core diagnosis, and material basis/scope. Omission is not withdrawal. A reporting gap is not evidence that an experiment was never performed. Known-issue recall requires a supported issue set fixed before generation; later discoveries are recorded separately. Invalid-concern persistence is undefined when no eligible invalid concerns exist. No overall article-quality score is formed.

Generated reviews, automatic role labels, and automatic scientific judgments must be identified as such. Human verification and independent adjudication cannot be claimed unless they actually occurred. The initial E0 quality audit was an exploratory, nonblind automated source assessment, not independent expert validation; it does not calibrate a gold standard for the pilot.

Each live attempt receives a unique identifier and preserves its request, response when available, exact returned model identifier, timestamps, usage, conservative fee bound, and parent records. Explicit transient service errors may receive at most two additional same-input attempts. Transport ambiguity is retained as unknown and is not blindly resent. Failed or truncated reviews are not passed into later generations.

Models, manuscript versions and hashes, effective sampling, segmentation and annotation rules, evidence policies, endpoints, retry handling, audit sampling, and total budget are fixed before the pilot. Full review histories and external retrieval are disabled during generation. Evaluation resources and missingness must be reported consistently across conditions.

The three recent papers have arXiv v1 dates after 2026-04-30 and use the latest available version checked on 2026-11-18. This date rule is an operational exposure proxy, not proof of training exclusion. Topic matching does not remove differences in publication status, age, study design, or length, so old-versus-recent comparisons are descriptive.

The public source has portability and publication edits. It is not a replacement for the frozen inputs or source bytes of an existing local run. Prepare a fresh run and preserve its own source revision before live execution.
