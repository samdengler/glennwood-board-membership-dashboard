# Glennwood Estates board dashboard

A small static dashboard of membership contributions, rebuilt nightly from
the Zeffy API and published to GitHub Pages.

## How it works

1. A scheduled GitHub Actions workflow (`.github/workflows/refresh-dashboard.yml`)
   runs nightly, calls the Zeffy API for payments and contacts, and computes
   the totals, monthly trend, membership mix, and household list.
2. Those figures are baked into `site/template.html` and published to
   GitHub Pages.
3. The page sits behind a client-side password gate. **This is a
   convenience gate, not real security** &mdash; anyone who views the page
   source can see the figures. It keeps the page off search engines and
   out of casual view, nothing more. If the board ever wants real
   per-person access control (e.g. Cloudflare Access, gated by each
   member's email), that's a bigger but still free upgrade.

## One-time setup

1. **Get a Zeffy API key.** In Zeffy, go to Settings &rarr; Integrations,
   choose "API", answer the qualifying questions, and generate a key. Only
   an account admin can do this.
2. **Add it as a repo secret.** In this repo: Settings &rarr; Secrets and
   variables &rarr; Actions &rarr; New repository secret.
   - Name: `ZEFFY_API_KEY`
   - Value: the key from step 1
3. **Pick a shared board password and hash it** (the plaintext password is
   never stored anywhere in this repo):
   ```
   python3 scripts/hash_password.py
   ```
   Paste the printed hash as a second repo secret:
   - Name: `DASHBOARD_PASSWORD_HASH`
   - Value: the hash printed above
4. **Turn on GitHub Pages.** Settings &rarr; Pages &rarr; Build and
   deployment &rarr; Source: **GitHub Actions**.
5. **Run it once by hand.** Actions tab &rarr; "Refresh board dashboard" &rarr;
   Run workflow. After it finishes, the Pages URL (shown in the workflow's
   `deploy` job) is the dashboard link to share with the board, along with
   the password out of band (text or in person, not email).

After that, it refreshes on its own every night at 09:15 UTC. You can
always trigger an early refresh from the Actions tab before a board
meeting.

## Changing the password later

Re-run `python3 scripts/hash_password.py`, update the
`DASHBOARD_PASSWORD_HASH` secret, and re-run the workflow (or wait for the
next nightly run).

## If Zeffy's API fields don't match

`scripts/build_dashboard.py` was written against Zeffy's published API
reference. If a field has moved, the workflow log includes
`build_debug.json` with one raw payment and one raw contact record as
Zeffy actually returns them (this file is never committed) &mdash; check
it against the field names near the top of `build_dashboard.py`
(`line_item_label`, `line_item_recurring`, `first_present` calls) and
adjust.
