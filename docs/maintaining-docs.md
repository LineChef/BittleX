# Maintaining the docs

Working notes for whoever edits the documentation. This page is not published on the site: the site shows only the reader-facing pages (see "What is published" below).

## Where to update what

One home per fact; everything else links. Don't restate the deployed policy, a status, or a test count anywhere else —
`python tools/check_docs.py` (run by the pre-commit hook) fails on broken links, hard-coded test counts, and the policy name in the wrong page.

- A run, test or measurement: the relevant dated log: [`rl/real-walk-log.md`](rl/real-walk-log.md) (real robot; what each hardware log carries: [`rl/hardware-logging.md`](rl/hardware-logging.md)), [`rl/hw1-log.md`](rl/hw1-log.md) (training), other `rl/*` logs; raw data goes in `~/g2_data/real_walk_data/` (outside the repository; the earlier logs are in git history)
- A state change (new policy deployed, hardware fixed or broken, something tested for the first time): [`STATUS.md`](STATUS.md) — plus a line in the log that holds the detail
- A capability lands or is parked: [`capabilities.md`](capabilities.md) (and [`STATUS.md`](STATUS.md) if it changes what is deployed)
- A decision is made or a phase item is done: the entry in [`project-plan.md`](project-plan.md) (checkbox + one line + link to the detail)
- A backlog item changes status: its own heading in `planned/hardware-gated-backlog.md`, `planned/robustness-backlog.md` or `planned/behavior-ideas.md`, then `python tools/gen_backlog.py` ([`backlog.md`](backlog.md) is generated)
- The deployed policy changes: `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` and [`STATUS.md`](STATUS.md); nowhere else names it
- Wiring, pinouts, assembly: [`../blueprints/README.md`](../blueprints/README.md); vendor specs in [`hardware/specs.md`](hardware/specs.md); firmware tokens in [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md)
- Scratch / temp files pile up (Mac or Pi): `python tools/g2_cleanup.py` (`g2clean`): dry run lists them, `--apply` deletes by exact path and cleans the Pi's `trained/` folder; a hook reminds on every prompt and the pre-commit hook warns about leftovers and blocks adds of >150 files or >5 MB
- A command worth remembering: [`guides/cheatsheet.md`](guides/cheatsheet.md) (everyday commands first, rare ones after them, one example per row)
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

- Write a section heading as its title on its own line over a line of `---`, never as `## Title` (the page title stays `# Title`, and sub-sections stay `###`). A title that would start like a list item escapes its first marker (`1\\. Title`). `python tools/md_headings.py FILE` converts a page, and `python tools/check_docs.py` fails on a `##` in a published page.
- Never wrap a title in `**` bold. The title of a list item or a paragraph is its plain lead followed by a colon (`Orientation: G2 is never placed on his back.`); the bundle renders the text before the first colon as an `h4` (see [the bundle guide](guides/docs-bundle.md), "Semantic HTML"), and the site styles it by tag.

Adding new content
------------------

New content follows the structure the site has now, so a new page reads like the existing ones and the build accepts it.

Where it goes:
- A subsystem (how something behaves, its settings, how to verify it): `specification/<name>.md`, in the sections Behaviour, Interfaces, Parameters, Constraints, Failure handling and Verification. A change to what a subsystem does updates its page in the same commit.
- A procedure someone follows (set up, operate, configure, train): `guides/<name>.md`, with prerequisites, numbered steps with exact commands, the expected result and a pass check.
- Hardware facts and parts: `hardware/`. Camera and detection: `vision/`. Training and the real-data pipeline: `rl/`. The physical build record, with its renders and wiring: `blueprints/`.
- What is true now, deployed, tested or broken: [`STATUS.md`](STATUS.md) only. Dated findings, plans, run logs and decisions go in `plan-detail/`, `planned/` or the dated `rl/` logs, which the site does not publish.
- A command: the cheat sheet. A setting: [`guides/settings-switches.md`](guides/settings-switches.md). Never restate either in a subsystem page beyond the one line that names it.

What a new published page needs, in one commit:
1. The page, with an opening paragraph that says what the page is and who needs it (the site uses it as the summary), and optional front matter (`audience`, `kind`).
2. A short nav title in `docs/nav-titles.json` (a top-level page is at most two words and 22 characters, a child at most four words and 30) and a place in `docs/nav-order.json`, most important first. The build fails on a page with no place.
3. A link from its folder README, and from `docs/README.md` when it is a top-level page, so it is not an orphan.
4. Links to other pages written as relative paths to the `.md` file. A link to a working note, or to a page that is left out of the site, fails the build.
5. Any new setting in `settings-switches.md`, any new command in the cheat sheet, and the fact it changes in `STATUS.md`.

How it is written, in short (each rule is explained under "Writing a published page" and "Images"):
- A specification, not notes: present tense, no people, no dates, no first person, no history, and no instructions to a coding assistant.
- Sections are a title line over `---`, never `## Title`. Sub-sections use `###`. The page title is `# Title`.
- A list item or a paragraph that has a title starts with the plain title and a colon (`Orientation: G2 is never placed on his back.`), never bold. There are no pipe tables.
- A figure is an image alone on a line with alt text and a caption, and it respects the size rules. A picture from another project carries its credit in the caption and an entry in `blueprints/images/SOURCES.json`.
- A requirement is a plain statement, with its reason in one line if it needs one. What is not built yet is said once, in `STATUS.md`.

Before committing:
- `python tools/check_docs.py` passes (errors block the commit), and `python tools/check_docs.py --notes` lists nothing for the new page.
- `python tools/build_docs_bundle.py --out <scratch folder> --branch development --assets-url https://linechef.github.io/BittleX/assets` builds, which checks the nav, the links and the images.
- Generated pages (`backlog.md`, the shell helpers page and the cheat sheet's A to Z index) are regenerated with `g2docsgen`, never edited by hand.
- When a page is deleted or renamed, every link to it is updated or removed in the same commit (`python tools/check_docs.py` lists the broken ones), its nav entries are removed, and a code comment that cites it is updated.

Starting point for a specification page:

```
---
audience: contributor
kind: reference
---

# Subsystem name

One or two sentences: what the subsystem does and what it connects to, with a link to the page that covers the guards or the setup.

Behaviour
---------

- Title: What it does, as a plain statement.

Interfaces
----------

- Input: What it reads.
- Output: What it sends.

Parameters
----------

- `G2_SETTING`: What it sets and its default

Constraints
-----------

- Title: A rule that always holds, with its reason in one line.

Failure handling
----------------

- Title: What happens when this fails.

Verification
------------

- Tests: The command that covers it with no hardware.
- Robot: The check to run on G2 and its pass criterion.
```

Starting point for a guide:

```
# Task name

What the task achieves, who does it, and what it needs.

Before you start
----------------

- Prerequisites, each one a plain statement.

Steps
-----

1. Do this: `command`.
2. Check this: the expected result.

Check
-----

- Pass criterion: What shows the task worked.
```

Background jobs on the Mac
--------------------------

`g2bg` (`tools/g2_bg_jobs.sh`, with `g2bg status|stop|start`, logs in `~/g2_logs/`) runs `tools/g2_sync.sh` (`g2sync`) every 30 minutes. It copies everything from the Pi to the Mac, each item on its own schedule:
- Goal data and **exploration pictures**, with curation by `tools/g2_curate_auto.sh`.
- Run logs, with ingest and the calibration step (`tools/g2_cal_auto.sh`).
- Wall pictures, every 30 minutes.
- A memory database snapshot and **the logs**, once a day.

`g2sync status` shows when each copy last worked and flags a stale one. The review page shows the same line under its title and has a **Sync from the Pi** button. The job skips quietly while the Pi is off or busy (an exploration, a goal session, a walk or a hardware test), ends at a Mac restart, and runs a snapshot's harm check only when the Mac is idle. launchd cannot run scripts under `~/Desktop` (macOS reports "Operation not permitted"), so a plain loop runs the job.

Calibration approval is automatic through statistical gates ([Real-data pipeline](rl/real-data-pipeline.md)), and `g2cal revert` undoes it.

Working in the repository
-------------------------

- A command chain that must stop on a failing test uses `&&` before committing, because `;` continues past a failure.
- A failing pytest assertion can print a settings object. Tests compare plain numbers, and full-suite output is filtered for `sk-ant` before it is shared.
- The privacy hook flags personal names in docs and docstrings, so tracked files use placeholders.
- Committing is local. `git push origin development` is a deliberate step, because the repository is public.
- Capture folders, `trained/` files and the memory database are looked at before deleting, because they are not all reproducible.

Images
------

- Where: Images for published pages live in `blueprints/images/` (the build record) and `docs/images/` (everything else). Photos are allowed, and a photo is checked for anything private before it is committed. GIFs are never committed.
- Format: Diagrams are SVG, drawn by hand or generated from the measurements in the docs. Renders and photos are PNG or JPEG. An SVG has no script, `foreignObject`, event handler or reference to anything outside the file.
- Size: A raster image is at most 300 KB (resize or recompress it), and all the images together stay under 5 MB. `python tools/check_docs.py` fails on a breach.
- Markup: `![Alt text](images/pod-rear.png "Caption")` on a line of its own becomes a figure with a caption. Alt text says what the picture shows, and the caption carries the credit for a picture that is not ours.
- Credits: A picture from another project keeps its licence. `blueprints/images/SOURCES.json` lists each file's source project, path, commit and licence, and the figure caption names the author.
- The bundle: Each image is exported as an asset with its pixel size and the pages that use it. A small SVG is written into the page HTML, so the site's CSS reaches it. See [the bundle guide](guides/docs-bundle.md), "Images".
