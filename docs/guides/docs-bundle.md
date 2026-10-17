# The docs bundle: showing these docs on a website

Every documentation page in the repo is packaged, on every push, as a **bundle** of plain files that a website can read and render as its own pages. There is no server or API to run: the bundle is static files on GitHub Pages. This page describes how it is built and published, the file format, and how the React site (Vite) loads it. Build code: [`../../tools/build_docs_bundle.py`](../../tools/build_docs_bundle.py); the workflow: `.github/workflows/docs-bundle.yml`.

## How it is built and published

1. A push to `development` starts the `docs-bundle` GitHub Action.
2. It runs the docs checks first (`check_docs.py`: broken links, stale generated pages). A failing check stops the build, so a broken page is never published.
3. `build_docs_bundle.py` reads **git-tracked files only**, so nothing gitignored (`CLAUDE.md`, training data, local pictures) can reach it. If a local `.gitprivacy-terms` file exists, the build also refuses to publish a bundle that contains one of its terms (the file is not in CI; the pre-commit hook enforces it there).
4. The bundle is published to GitHub Pages at `https://linechef.github.io/BittleX/` (after Pages is enabled once: repository Settings, Pages, Source: GitHub Actions).
5. Optionally, if the repository secret `SITE_DEPLOY_HOOK` holds a deploy-hook URL (Vercel, Netlify and similar), the Action asks the site to rebuild after publishing.

Build it locally with `g2bundle` (output in `build/docs-bundle/`, gitignored).

## What is in the bundle

| File | What it is |
|---|---|
| `latest.json` | A tiny pointer: `version`, `built`, the names of the other files, page and asset counts. Fetch this first; it changes whenever any page changes |
| `manifest.json` | The navigation tree (`nav`), every page's metadata (`pages`), the assets list, and the settings the links were built with (`base`, `assetsUrl`, `repo`, `branch`) |
| `search.json` | One plain-text record per page (title, headings, the first 4,000 characters) for a client-side search library |
| `pages/<route>.md` | Each page's Markdown with its links already rewritten. `pages/index.md` is the home page |
| `assets/<repo path>` | Images, PDFs and the standalone HTML pages (the wiring guide, the AI Head plan) |

A **page** entry has `route`, `title`, `section`, `source` (the repo path), `updated` (the date of its last commit), `summary` and `headings` (`level`, `text`, `id`). Sections: `overview`, `guides`, `hardware`, `vision`, `rl`, `research`, `plan-detail`, `planned`, `archive`, `blueprints`, `code`, `about`. The `nav` tree is ordered the way each folder's README lists its pages.

**Routes:** `docs/guides/cheatsheet.md` is `guides/cheatsheet`; a folder's `README.md` is the folder route; `docs/README.md` is the home page (`""`); `blueprints/...` keeps its path; code READMEs live under `code/` (`code/pi_pipeline/voice`); the repository README is `about`.

**Links** inside pages are rewritten when the bundle is built: a link to another page becomes `<base>/<route>#anchor` (default base `/docs`), a link to an asset becomes `<base>/_assets/<repo path>`, and a link to a file that is not a page (a script, for example) becomes a GitHub link on the `development` branch. Serve the bundle's `assets/` folder at `<base>/_assets/` in the site, or change the links with `--base` and `--assets-url` at build time.

## Order and groups in the navigation

The order of the pages in the site's sidebar is the order of the rows in each folder's `README.md`: change the order of the rows and rebuild. A page the README does not list goes to the end, alphabetically. A `###` heading in a folder README makes a **sidebar group**: the pages linked under it carry a `group` field in the manifest's `nav` (for example `Operate` and `Configure` under Guides). Use a `###` heading only for a group; `##` headings are ordinary sections. Pages above the first `###` have no group and come first.

The order of the top-level overview pages is set in the builder (`TOP_ORDER` in `build_docs_bundle.py`), and the folders follow `FOLDER_ORDER`.

## Loading it from the React site (Vite)

The site is a single-page app, so the simplest reliable approach is to **fetch the bundle at run time** from GitHub Pages, which allows cross-origin reads:

1. Fetch `latest.json`, then `manifest.json?v=<version>` and `search.json?v=<version>`; the version in the query string makes the browser cache each file until the docs change.
2. Fetch a page with `pages/<route>.md?v=<version>` when its route is opened.
3. Render the Markdown, with a router for `<base>/*`, a sidebar from `manifest.nav`, and links turned into router links.

Libraries the site would add: `react-router-dom`, `react-markdown` with `remark-gfm` (tables), `rehype-slug` (heading ids for the anchors), `rehype-sanitize`, a code highlighter, `minisearch` (search) and `mermaid` (loaded on demand: the architecture page has a diagram). The standalone HTML pages open in a sandboxed `iframe` or a new tab.

```ts
// src/docs/bundle.ts: a sketch, in the repo's TypeScript style
const BUNDLE = import.meta.env.VITE_DOCS_BUNDLE_URL ?? 'https://linechef.github.io/BittleX'

export interface NavNode { route: string; title: string; section: string; children?: NavNode[] }
export interface Manifest { version: string; base: string; nav: NavNode[]; pages: { route: string; title: string; summary: string }[] }

let manifest: Promise<Manifest> | undefined
export function loadManifest(): Promise<Manifest> {
  manifest ??= fetch(`${BUNDLE}/latest.json`).then((r) => r.json())
    .then((l: { version: string; manifest: string }) => fetch(`${BUNDLE}/${l.manifest}?v=${l.version}`).then((r) => r.json()))
  return manifest
}
export async function loadPage(route: string): Promise<string> {
  const { version } = await loadManifest()
  return fetch(`${BUNDLE}/pages/${route || 'index'}.md?v=${version}`).then((r) => r.text())
}
```

The site's navigation (Home, Status, Hardware, Walking, Pipeline) can point at the bundle's routes: Status is `STATUS`, Hardware is `hardware` (start with `hardware/as-built`), Walking is `rl` (start with `rl/walking-policy`), Pipeline is `code/pi_pipeline`.

**Build-time alternative.** If you would rather have the docs shipped with the site (same origin, no run-time fetch), copy the bundle into the site's `public/docs-bundle/` before `vite build` and point `VITE_DOCS_BUNDLE_URL` at it; the deploy hook above rebuilds the site whenever the docs change. Prerendering the pages (for search engines) would need an extra step, such as a static-site plugin for Vite.

## Keeping it healthy

- `python tools/check_docs.py` (alias `g2check`) must pass; the bundle build runs it.
- `python tools/build_docs_bundle.py` prints a warning for any link whose target is missing; the count should stay at 0.
- The format above is the contract with the site. A change to the manifest fields should be made in the builder, this page and the site's loader together.
