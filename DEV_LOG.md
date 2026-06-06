## 2026-06-02
- Set up Snowflake schema and loaded sample data for 10 customers
- Wrote ARR, MRR trend, NRR, and churn queries (all running clean)
- Built semantic model YAML using Cursor, specific to Cortex Analyst schema w/ dimensions, facts, synonyms, and sample values
- Learned: SYSADMIN role required to create databases, PUBLIC role insufficient

- Set up skeleton for streamlit app, 2 tabs: Q/A and 3 dashboards w/ placeholders
- Learned: .gitignore keeps the local credentials from being pushed (alternative to normal .env approach)

## 2026-06-05
Wired Cortex Analyst into Ask a Question tab:
- Cortex was returning "requires more information" for every question
- Root cause: semantic model YAML had lowercase column and table names
- Snowflake identifiers are uppercase by default: YAML must match exactly
- Fix: updated all column names, table names, and references to uppercase
- Lesson: always check actual Snowflake object names with SHOW TABLES and 
  DESC TABLE before writing a semantic model

  ## 2026-06-06
- Verified all three core metrics working: total ARR, MRR by month, churned customers
- Built three live dashboard charts using Plotly:
  - ARR Trend: line chart showing total annual contract value by subscription 
    start month — gives a snapshot of when revenue was committed over time
  - NRR by Cohort: bar chart showing net revenue retention percentage per 
    cohort month with a 100% break-even reference line — shows whether each 
    customer cohort is expanding, flat, or contracting over time
  - Churn Rate: line chart showing monthly customer churn rate as a percentage 
    (identifies which months had customer losses)
- Learned: st.cache_data prevents redundant Snowflake queries on every 
  Streamlit rerender — important for credit management on trial account
- App is functionally complete — Cortex Analyst + dashboards both working

