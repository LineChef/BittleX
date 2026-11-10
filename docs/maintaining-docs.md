# Maintaining the docs

Working notes for whoever edits the documentation. This page is not published on the site: the site shows only the reader-facing pages (see "What is published" below).

## Where to update what

One home per fact; everything else links. Don't restate the deployed policy, a status, or a test count anywhere else —
`python tools/check_docs.py` (run by the pre-commit hook) fails on broken links, hard-coded test counts, and the policy name in the wrong page.

| When this happens | Write it here — and only here |
|---|---|
| A run, test or measurement | the relevant dated log: [`rl/real-walk-log.md`](rl/real-walk-log.md) (real robot; what each hardware log carries: [`rl/hardware-logging.md`](rl/hardware-logging.md)), [`rl/hw1-log.md`](rl/hw1-log.md) (training), other `rl/*` logs; raw data goes in `rl/real-walk-data/` |
| A state change (new policy deployed, hardware fixed or broken, something tested for the first time) | [`STATUS.md`](STATUS.md) — plus a line in the log that holds the detail |
| A capability lands or is parked | [`capabilities.md`](capabilities.md) (and [`STATUS.md`](STATUS.md) if it changes what is deployed) |
| A decision is made or a phase item is done | the entry in [`project-plan.md`](project-plan.md) (checkbox + one line + link to the detail) |
| A backlog item changes status | its own heading in `planned/hardware-gated-backlog.md`, `planned/robustness-backlog.md` or `planned/behavior-ideas.md`, then `python tools/gen_backlog.py` ([`backlog.md`](backlog.md) is generated) |
| The deployed policy changes | `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` and [`STATUS.md`](STATUS.md); nowhere else names it |
| Wiring, pinouts, assembly | [`../blueprints/README.md`](../blueprints/README.md); vendor specs in [`hardware/specs.md`](hardware/specs.md); firmware tokens in [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) |
| Scratch / temp files pile up (Mac or Pi) | `python tools/g2_cleanup.py` (`g2clean`): dry run lists them, `--apply` deletes by exact path and cleans the Pi's `trained/` folder; a hook reminds on every prompt and the pre-commit hook warns about leftovers and blocks adds of >150 files or >5 MB |
| A command worth remembering | [`guides/cheatsheet.md`](guides/cheatsheet.md) (everyday, one example per row); rare ones in [`guides/cheatsheet-advanced.md`](guides/cheatsheet-advanced.md) |
| A research question or vendor evaluation | [`research/`](research/) |

## What is published

`tools/build_docs_bundle.py` builds the docs site's content. Working notes stay in the repo but are left out: `plan-detail/`, `planned/`, `archive/`, `research/`, the run logs in `rl/` (`real-walk-log`, `hw1-log`, `results-index` and the other dated logs), `backlog.md` and this page (the list is `EXCLUDED_DIRS` / `EXCLUDED_FILES` in the builder). A published page must not link to a working note: the build fails and names the link.

## Writing a published page

- Write for a person who has never seen the repo. State what the page is and who needs it in the first one or two sentences; the builder uses that opening paragraph as the page summary.
- Use an instructional, explanatory voice. No "I", "you" or "we", and no mention of Claude or the person who decided something. Use imperatives for steps ("Open the cheat sheet") and plain statements for facts.
- Describe the current state. Keep dated decisions, who asked for what and how a conclusion was reached in the working notes.
- Keep table cells short (under about 40 words). Put a longer explanation under a heading as a paragraph or list.
- Define a term the first time it appears (BiBoard, residual policy, eased stand-up).
- Optional front matter sets who a page is for and what it is: `audience: visitor | builder | contributor` and `kind: overview | guide | reference | concept`. Without it the section's default applies (`SECTION_DEFAULTS` in the builder).
- `python tools/check_docs.py` warns about long table cells, very long lines (over 700 characters), attribution tags such as "(user, 2026-...)" and a missing opening paragraph in published pages.
