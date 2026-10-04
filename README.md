# AI-Powered Finance Analytics App

**Repo:** `snowflake-finance-analytics`

A Streamlit in Snowflake (SiS) app for SaaS revenue analytics. Finance users can ask revenue questions in plain English, check three executive dashboards, and generate a quarterly revenue briefing. Python computes the numbers and a Snowflake Cortex LLM writes the narrative.

**Demo video:** https://youtu.be/Ub1w8yCGPeU

![Ask a Question tab answering "What is the total ARR?" through Cortex Analyst](screenshots/SS%20First%20run%20in%20Snowflake/Screenshot%202026-06-06%20at%201.25.26%E2%80%AFPM.png)

## What it does

The app (`app/main.py`) has three tabs.

### 1. Ask a Question (Cortex Analyst)

- You type a question such as "What is total ARR?" or "How many customers churned?".
- The app sends it to the Cortex Analyst REST API (`/api/v2/cortex/analyst/message`) with the semantic model `semantic_model/finance_model.yaml`, loaded from the stage `@FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE`.
- Cortex Analyst returns SQL. The app runs that SQL through Snowpark and shows the result as a table.
- If Cortex Analyst cannot produce SQL, the app shows its explanation and suggested questions instead.

The semantic model covers three tables (`CUSTOMERS`, `SUBSCRIPTIONS`, `MONTHLY_REVENUE`). It defines dimensions, measures, metrics (`total_arr`, `total_mrr`, `churned_customers`), synonyms, sample values, relationships, and four verified queries.

### 2. Dashboards

There are three Plotly charts, each built from a fixed SQL query and cached for 10 minutes with `st.cache_data`:

| Chart | What it measures |
|---|---|
| **ARR Trend** | Annual contract value of active subscriptions, grouped by subscription start month (new ARR booked per month, not a running total) |
| **NRR by Cohort** | Customers grouped by first-revenue month; each cohort's current MRR (each customer's MRR in their latest recorded month, 0 if churned) as a percentage of its starting MRR (MRR in the cohort month), with a 100% break-even line |
| **Churn Rate** | Share of customers with a prior month on record whose MRR dropped from above zero to zero that month |

![ARR Trend chart in the deployed app](screenshots/SS%20First%20run%20in%20Snowflake/Screenshot%202026-06-07%20at%2010.08.53%E2%80%AFAM.png)

![NRR by Cohort chart with the 100% break-even line](screenshots/Updated%20NRR%20by%20Cohort%20SS.png)

*After the October 2026 NRR fix: cohorts run from 0% (the April and August customers churned) to 112.5%, with a weighted NRR of 101.3%. Before it, every bar read 100%.*

### 3. Workflow: quarterly revenue briefing

One button, **Generate Quarterly Revenue Summary**, runs a fixed finance process:

1. **Extract:** three SQL queries pull ARR by plan tier, NRR by cohort, and ARR by start month.
2. **Compute (Python, deterministic):**
   - total ARR
   - ARR by tier and each tier's share
   - combined ARR of all tiers below the top tier
   - NRR weighted by cohort starting MRR
   - newest start-month cohort ARR and its change from the prior cohort
3. **Narrate (Cortex COMPLETE):** the computed figures go into a structured prompt (context, rules, a few-shot example, output format), which is sent to `SNOWFLAKE.CORTEX.COMPLETE` with `mistral-large2`. The prompt tells the model to write three paragraphs (headline, tier concentration, one risk and one opportunity) using only the numbers it was given, without deriving new ones.

The tab shows four KPI tiles (Total ARR, Weighted NRR, Newest Cohort ARR, Top Tier Share) above the executive summary.

![Workflow tab with KPI tiles and the generated executive summary](screenshots/SS%20Agentic%20workflow%20tab/Screenshot%202026-06-07%20at%204.20.18%E2%80%AFPM.png)

*This capture was taken before the fix that escapes `$` in the narrative. That is why parts of the summary render as math text. The current code escapes `$` before calling `st.markdown`.*

## Architecture

```text
Snowflake account
|
+-- FINANCE_ANALYTICS.CORE
|     CUSTOMERS, SUBSCRIPTIONS, MONTHLY_REVENUE     synthetic demo data
|     STREAMLIT_STAGE                               finance_model.yaml (+ app files)
|
+-- Streamlit in Snowflake app (app/main.py, Snowpark get_active_session())
      |
      +-- Ask a Question --> Cortex Analyst REST API via _snowflake.send_snow_api_request
      |                      (semantic model from the stage) --> generated SQL
      |                      --> Snowpark --> results table
      |
      +-- Dashboards ------> 3 fixed SQL queries (st.cache_data, 10 min) --> Plotly charts
      |
      +-- Workflow --------> 3 SQL queries --> KPIs computed in Python
                             --> SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', prompt)
                             --> 3-paragraph executive summary
```

Everything runs inside Snowflake: the app uses the active Snowpark session and the built-in `_snowflake` module, so no credentials are handled in app code.

### Repo layout

| Path | Contents |
|---|---|
| `app/main.py` | The Streamlit app (all three tabs); deployed to the stage as `streamlit_app.py` |
| `app/environment.yml` | Package spec for the deployed app (Snowflake Anaconda channel: `plotly=5.24.1`) |
| `app/pyproject.toml` | Project file stored with the deployed app (Python 3.11, `streamlit[snowflake]`, `plotly==5.24.1`) |
| `semantic_model/finance_model.yaml` | Cortex Analyst semantic model |
| `sql/metrics.sql` | Standalone metric queries: ARR by customer, MRR trend with month-over-month growth, NRR by cohort, monthly churn rate |
| `.streamlit/secrets.toml.example` | Template for a local Snowflake connection (placeholders only) |
| `data/sample_data.sql` | The demo dataset: table DDL and all rows for CUSTOMERS (10), SUBSCRIPTIONS (10) and MONTHLY_REVENUE (29), exported from Snowflake |
| `screenshots/` | Screenshots from each build stage |
| `DEV_LOG.md` | Day-by-day build log |

## Setup

Requirements: a Snowflake account where Cortex Analyst and Cortex COMPLETE (`mistral-large2`) are available, a warehouse, and a role that can create databases (the build used `SYSADMIN`; `PUBLIC` is not enough).

**1. Create the database, schema, tables, and stage.**

```sql
USE ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS FINANCE_ANALYTICS;
CREATE SCHEMA IF NOT EXISTS FINANCE_ANALYTICS.CORE;

-- Create and load CUSTOMERS, SUBSCRIPTIONS and MONTHLY_REVENUE:
-- run data/sample_data.sql (table DDL plus the demo rows).

CREATE STAGE IF NOT EXISTS FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE;
```

**2. Upload the semantic model and app files to the stage.** `PUT` runs from SnowSQL, the Snowflake CLI or a connector, not from a Snowsight worksheet. It keeps the local file name, so copy `app/main.py` to `streamlit_app.py` first (the name the deployed app runs). Use absolute paths, and keep `AUTO_COMPRESS=FALSE` so the files stay readable at the exact paths the app expects (for example `@FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE/finance_model.yaml`):

```bash
cp app/main.py /tmp/streamlit_app.py
```

```sql
PUT 'file:///<path-to-clone>/semantic_model/finance_model.yaml' @FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
PUT 'file:///tmp/streamlit_app.py'                              @FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
PUT 'file:///<path-to-clone>/app/environment.yml'               @FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
PUT 'file:///<path-to-clone>/app/pyproject.toml'                @FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
```

SiS installs packages from the Snowflake Anaconda channel, not PyPI (Anaconda pins use a single `=`). Streamlit, pandas, and Snowpark come with the runtime; the app also needs Plotly, which `app/environment.yml` pins.

**3. Create the Streamlit app.**

```sql
CREATE STREAMLIT FINANCE_ANALYTICS.CORE.FINANCE_ANALYTICS_APP
  ROOT_LOCATION = '@FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE'
  MAIN_FILE = 'streamlit_app.py'
  QUERY_WAREHOUSE = <your_warehouse>;
```

If you change `environment.yml` later, `DROP STREAMLIT` and `CREATE` it again. `ALTER STREAMLIT ... SET MAIN_FILE` does not rebuild the package environment.

**Secrets.** For a local Snowflake connection, copy the template and fill in your own values:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

`.streamlit/secrets.toml` is gitignored; never commit it. It holds a `[connections.snowflake]` block, the format `st.connection("snowflake")` reads. The earlier local build of the app used it. The deployed SiS app does not read it: it uses `get_active_session()`. Because `app/main.py` imports `_snowflake`, which exists only inside Streamlit in Snowflake, the current app runs in Snowflake rather than with a local `streamlit run`.

## Data

The data is a **synthetic SaaS dataset with 10 customers**, built for this demo (customers, subscriptions, and monthly revenue records with movement types: new, renewal, expansion, contraction, churn). It lives in a Snowflake account (`FINANCE_ANALYTICS.CORE`); `data/sample_data.sql` recreates it (DDL and every row). No real customer or company data is used.

## Key lessons

From `DEV_LOG.md` and the commit history:

- **The semantic model must match Snowflake identifiers exactly.** Cortex Analyst answered "requires more information" to every question until the YAML's lowercase table and column names were changed to uppercase. Run `SHOW TABLES` and `DESC TABLE` before writing a semantic model.
- **Streamlit in Snowflake is a different runtime.**
  - `st.connection` is not available there, so the app uses Snowpark `get_active_session()`.
  - Cortex Analyst is called through `_snowflake.send_snow_api_request()`, the supported path, which handles auth itself instead of reaching into private session internals.
- **Packages come from the Snowflake Anaconda channel** via `environment.yml`, and `ALTER STREAMLIT SET MAIN_FILE` only repoints the file. Only `DROP` + `CREATE` rebuilds the environment; earlier fixes did not take effect until the app was recreated.
- **Cache dashboard queries.** `st.cache_data` stops every Streamlit rerun from re-querying Snowflake, which matters for credits on a trial account.
- **Check metrics against the raw rows by hand.** NRR read 100% for every cohort until a per-customer check showed both sides of the ratio summed the same months; it now compares MRR in the cohort month with MRR in the latest month.
- **Let the LLM narrate, not calculate.** The model got the combined ARR of the non-top tiers wrong, so that figure moved into deterministic Python and the prompt now forbids deriving new numbers.
- **Escape `$` in LLM output before `st.markdown`.** Streamlit reads paired dollar signs as LaTeX.
- **Database creation needs the right role:** `SYSADMIN` works, `PUBLIC` does not.
- **Keep credentials out of git:** real values only in the gitignored `.streamlit/secrets.toml`; the committed example has placeholders.

## Known limitations

- **NRR horizon.** NRR compares each customer's first and latest recorded month, which spans only 2 to 3 months in the demo data, not a fixed 12-month window. Each demo cohort holds one customer.

## License

[MIT](LICENSE)
