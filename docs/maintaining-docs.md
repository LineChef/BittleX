# Maintaining the docs

Working notes for whoever edits the documentation. This page is not published on the site: the site shows only the reader-facing pages (see "What is published" below).

## Where to update what

One home per fact; everything else links. Don't restate the deployed policy, a status, or a test count anywhere else —
`python tools/check_docs.py` (run by the pre-commit hook) fails on broken links, hard-coded test counts, and the policy name in the wrong page.

- A run, test or measurement: the relevant dated log: [`rl/real-walk-log.md`](rl/real-walk-log.md) (real robot; what each hardware log carries: [`rl/hardware-logging.md`](rl/hardware-logging.md)), [`rl/hw1-log.md`](rl/hw1-log.md) (training), other `rl/*` logs; raw data goes in `rl/real-walk-data/`
- A state change (new policy deployed, hardware fixed or broken, something tested for the first time): [`STATUS.md`](STATUS.md) — plus a line in the log that holds the detail
- A capability lands or is parked: [`capabilities.md`](capabilities.md) (and [`STATUS.md`](STATUS.md) if it changes what is deployed)
- A decision is made or a phase item is done: the entry in [`project-plan.md`](project-plan.md) (checkbox + one line + link to the detail)
- A backlog item changes status: its own heading in `planned/hardware-gated-backlog.md`, `planned/robustness-backlog.md` or `planned/behavior-ideas.md`, then `python tools/gen_backlog.py` ([`backlog.md`](backlog.md) is generated)
- The deployed policy changes: `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` and [`STATUS.md`](STATUS.md); nowhere else names it
- Wiring, pinouts, assembly: [`../blueprints/README.md`](../blueprints/README.md); vendor specs in [`hardware/specs.md`](hardware/specs.md); firmware tokens in [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md)
- Scratch / temp files pile up (Mac or Pi): `python tools/g2_cleanup.py` (`g2clean`): dry run lists them, `--apply` deletes by exact path and cleans the Pi's `trained/` folder; a hook reminds on every prompt and the pre-commit hook warns about leftovers and blocks adds of >150 files or >5 MB
- A command worth remembering: [`guides/cheatsheet.md`](guides/cheatsheet.md) (everyday, one example per row); rare ones in [`guides/cheatsheet-advanced.md`](guides/cheatsheet-advanced.md)
- A research question or vendor evaluation: [`research/`](research/)

## What is published

`tools/build_docs_bundle.py` builds the docs site's content. Working notes stay in the repo but are left out: `plan-detail/`, `planned/`, `archive/`, `research/`, the run logs in `rl/` (`real-walk-log`, `hw1-log`, `results-index` and the other dated logs), `backlog.md` and this page (the list is `EXCLUDED_DIRS` / `EXCLUDED_FILES` in the builder). A published page must not link to a working note: the build fails and names the link.

## Writing a published page

- Write for a person who has never seen the repo. State what the page is and who needs it in the first one or two sentences; the builder uses that opening paragraph as the page summary.
- Use an instructional, explanatory voice. No "I", "you" or "we", and no mention of Claude or the person who decided something. Use imperatives for steps ("Open the cheat sheet") and plain statements for facts.
- Write a published page as a product specification, not as research notes. It states how the system works and how to reproduce it, in the present tense, and it never says who decided something, when, or how it was found out.
- Give each requirement as a plain statement ("Every stand-up is the eased stand-up."). A one-line reason may follow it ("The firmware's quick stand-up jerks the heading by 10 to 12 degrees."). Do not tell the story of an incident or a test round; that belongs in the working notes.
- Choose the page shape that fits. A subsystem specification covers purpose, behaviour, interfaces, parameters and defaults, constraints, failure handling and how to verify it. A procedure covers prerequisites, numbered steps with exact commands, the expected result and a pass criterion. A reference lists commands, switches and tokens, generated where possible.
- Put everything that does not work yet in [`STATUS.md`](STATUS.md) under "Known limitations", not scattered through other pages.
- "Claude" appears in a published page only as the language model G2 talks to. Instructions addressed to a coding assistant ("tell Claude...") have no place in it.
- Describe the current state. Keep dated decisions, who asked for what and how a conclusion was reached in the working notes.
- Do not write markdown tables (no `| a | b |` rows) anywhere in the docs. Use a bulleted list with one bullet per row: a plain lead (never bold), a colon, then the rest (`- Run G2 day to day: [Operating G2](guides/operating-g2.md)`). For several columns, follow the lead with `Header: value` pairs separated by semicolons. `python tools/check_docs.py` fails on a table, and `python tools/md_lists.py FILE` converts one.
- Define a term the first time it appears (BiBoard, residual policy, eased stand-up).
- Optional front matter sets who a page is for and what it is: `audience: visitor | builder | contributor` and `kind: overview | guide | reference | concept`. Without it the section's default applies (`SECTION_DEFAULTS` in the builder).
- `python tools/check_docs.py` blocks pipe tables and warns about very long lines (over 700 characters), attribution tags such as "(user, 2026-...)", note-taking wording (people, first person, dates and history in prose, instructions to a coding assistant) and a missing opening paragraph in published pages. `python tools/check_docs.py --notes` lists the wording per page.

- Never wrap a title in `**` bold. The title of a list item or a paragraph is its plain lead followed by a colon (`Orientation: G2 is never placed on his back.`); the bundle renders the text before the first colon as an `h4` (see [the bundle guide](guides/docs-bundle.md), "Semantic HTML"), and the site styles it by tag.
