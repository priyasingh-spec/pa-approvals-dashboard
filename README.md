# LAC Approvals Live Dashboard

Hourly-refreshed dashboard of LAC approved leads from Cars24 Financial Services. Hosted on GitHub Pages, fed by a GitHub Action that queries Snowflake on a cron schedule.

## What this is

A single-page dashboard that shows approved LAC leads with date filters, source filter, search, and CSV download. Built for Dhruv Bainsla (Sales Head, Refinance) to track new approvals throughout the day.

**Refresh cadence:** every hour, on the hour, via GitHub Actions cron.
**PII handling:** mobile numbers masked to `98XXXX5660` format. Customer names dropped entirely. No full customer identifiers leave Cars24's perimeter.

## Architecture

```
┌──────────────┐    ┌─────────────────┐    ┌────────────────┐    ┌──────────────┐
│  Snowflake   │───▶│ GitHub Action   │───▶│ data/*.json    │───▶│ index.html   │
│  CFSPL_NBFC  │    │ (hourly cron)   │    │ (committed)    │    │ (Pages)      │
└──────────────┘    └─────────────────┘    └────────────────┘    └──────────────┘
                          ↑
                    GitHub Secrets
                  (SF credentials)
```

The Action runs `scripts/fetch_approvals.py`, which:
1. Connects to Snowflake using credentials stored as repo secrets
2. Queries last 30 days of LAC approvals
3. Masks mobile numbers
4. Writes `data/approvals.json` and `data/last_updated.json`
5. Commits and pushes back to the repo, which auto-deploys to Pages

## One-time setup (~15 min)

### 1. Create a new GitHub repo

Create a private repo named something like `lac-approvals-dashboard`. Push these files to the `main` branch.

### 2. Enable GitHub Pages

- Settings → Pages
- Source: **Deploy from a branch**
- Branch: **main**, folder: **/ (root)**
- Save

Your dashboard URL will be `https://<your-org>.github.io/lac-approvals-dashboard/`.

### 3. Add Snowflake secrets

Settings → Secrets and variables → Actions → New repository secret. Add these:

| Secret name | Value |
|---|---|
| `SNOWFLAKE_USER` | Your Snowflake username |
| `SNOWFLAKE_PASSWORD` | Your Snowflake password |
| `SNOWFLAKE_ACCOUNT` | `cq31887-cars24cfspl` (the part before `.snowflakecomputing.com`) |
| `SNOWFLAKE_WAREHOUSE` | `COMPUTE_WH` (or whichever warehouse you want to use) |
| `SNOWFLAKE_ROLE` | The role with read access to the source tables |

**Recommended:** create a dedicated service account user in Snowflake (e.g. `LAC_DASHBOARD_BOT`) with read-only access to the three source tables, rather than using a personal Snowflake login. Ask Manik or the data eng team to provision this. The bot's password lives only in GitHub Secrets.

### 4. Trigger the first run

Actions tab → "Refresh LAC Approvals Data" → "Run workflow" → main → Run.

After the workflow completes (~30 seconds), the `data/approvals.json` file will be populated. Visit your Pages URL to see the dashboard live.

### 5. Share with Dhruv

Send him the Pages URL. He doesn't need a GitHub account or any login to view it. Browser bookmark, done.

## Repo structure

```
.
├── .github/workflows/refresh.yml    # Hourly cron job
├── scripts/fetch_approvals.py       # Snowflake query, JSON writer, PII masker
├── data/
│   ├── approvals.json               # Auto-updated hourly
│   └── last_updated.json            # Auto-updated hourly
├── index.html                       # The dashboard (no build step)
└── README.md                        # This file
```

## What Dhruv sees

- **4 KPI tiles**: Total approvals in range, Today, Yesterday, Last 7 days (with avg/day). Today shows delta vs yesterday.
- **Date range chips**: Today / Yesterday / 7 Days / MTD (default) / 30 Days.
- **Source filter** and **search box** (Lead ID or masked mobile).
- **Table**: one row per approval, sorted newest first. Approvals from the last 60 minutes are tagged "NEW" with an accent border on the left.
- **CSV download** of the current filtered view.
- **Refresh button** to force-reload the JSON from GitHub.

## Tweaks

### Refresh more frequently

Edit `.github/workflows/refresh.yml`:
- `'0 * * * *'` = hourly (current)
- `'*/30 * * * *'` = every 30 min
- `'*/15 * * * *'` = every 15 min

GitHub Actions has a 5-min minimum granularity and 2,000 free min/month for private repos. Hourly = 720 runs/month at ~30s each = 6 minutes used. Plenty of headroom.

### Add more channels (D2C, PhonePe, C2B)

In `scripts/fetch_approvals.py`, change `AND A.CHANNEL = 'LAC'` to `AND A.CHANNEL IN ('LAC','D2C','PHONEPE','C2B')` and add a Channel column to the SELECT. Then add a channel filter in `index.html` (clone the source filter logic).

### Change PII masking

In `scripts/fetch_approvals.py`, edit the `mask_mobile` function. Current behavior: `9876543210` → `98XXXX3210`. Options:
- Show none: return `""` for all
- Show more: change slicing to show first 4 + last 4

### Add disbursal status

Join to `CFSPL_NBFC_DB.PROD.LOAN_DISBURSAL_DATA_DETAILS` on `RUL_LEAD_ID = LOAN_ID` and add a disbursed flag. Useful to show what % of approvals actually disburse.

## Cost

- GitHub Actions: free (well under 2,000 min/month quota)
- GitHub Pages: free
- Snowflake: ~1 second of warehouse time per hourly query. Effectively zero on COMPUTE_WH

## Limitations

- **Refresh granularity** is hourly. For near-real-time, switch to Streamlit-in-Snowflake.
- **PII is masked**, so Dhruv cannot call customers directly from this view. He needs Saarathi or another internal tool for full mobile numbers.
- **JSON file is public** if the repo is public. Keep the repo private OR ensure mobile masking is enforced before any data leaves Snowflake.
- **No authentication on the Pages URL** in this version. If you need basic auth, layer Cloudflare Access or a simple JS password gate on top.

## Maintenance

If queries break (schema change at Cars24), the Action will fail and you'll get an email. Check the Actions tab logs, fix the SQL in `scripts/fetch_approvals.py`, push, done.

If the schedule stops running for >60 days of repo inactivity, GitHub auto-pauses scheduled workflows. Just push any commit or click "Enable workflow" to resume.
