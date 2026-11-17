# Development E0

E0 is a separate development profile: one fixed manuscript, three shared starting reviews, and two updates under recursive and independent conditions (15 planned generation slots). It checks source lineage, status handling, budget accounting, and automatic structural measurement. It is not a formal pilot.

Use Python 3.12 on Windows, install the pinned requirements, and run the offline tests first. Inspect the coordinator entry points with `python experiment/src/development_e0.py --help`. Preparation, live execution and reporting are distinct operations. Preparation does not itself authorize charges.

Before live execution, configure the intended provider and endpoint, the matching environment variable, exact model identifier, effective sampling, manuscript source and hash, a current price record, and a hard total budget. Do not use the historical pair-launch examples as permission to rerun archived experiments or to send a credential to a different service.

`development_e0.py` contains the single-coordinator journal and reservation logic. `resume_e0_network_recovery.py` provides an explicitly configured environment-proxy transport; this class must be selected deliberately in environments that require a managed proxy. The base adapter disables environment proxies. Recovery is a recorded source revision rather than a silent transport substitution.

Keep every attempted request. An interrupted response whose upstream outcome is unknown retains its reservation and is not blindly resent. Do not place failed, empty or truncated reviews into later rounds. API outputs and local configuration are excluded from version control by default.

The shipped configuration is inactive. Extend from a fresh, explicitly configured development run; do not rewrite an earlier run's frozen files. A six-paper pilot needs its own manuscript and analysis locks, not a larger value inserted into an old E0 manifest.
