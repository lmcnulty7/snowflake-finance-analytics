"""Finance Analytics Streamlit application.

Includes an agentic Workflow tab that encodes a repeatable quarterly revenue
briefing: SQL extraction, deterministic KPI computation in Python, and Cortex
COMPLETE narration using only pre-computed figures.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import _snowflake
import pandas as pd
import plotly.express as px
import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()

APP_TITLE = "Finance Analytics"
SESSION_LAST_QUESTION = "last_question"
SESSION_LAST_RESULT = "last_result"
SESSION_WORKFLOW_METRICS = "workflow_metrics"
SESSION_WORKFLOW_NARRATIVE = "workflow_narrative"
CACHE_TTL = timedelta(minutes=10)
CORTEX_ANALYST_API_ENDPOINT = "/api/v2/cortex/analyst/message"
API_TIMEOUT_MS = 30000
SEMANTIC_MODEL_FILE = "@FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE/finance_model.yaml"

ARR_TREND_SQL = """
SELECT
    DATE_TRUNC('month', START_DATE) AS start_month,
    SUM(ANNUAL_CONTRACT_VALUE) AS total_arr
FROM FINANCE_ANALYTICS.CORE.SUBSCRIPTIONS
WHERE STATUS = 'active'
GROUP BY DATE_TRUNC('month', START_DATE)
ORDER BY start_month
"""

NRR_BY_COHORT_SQL = """
WITH customer_first_month AS (
    -- cohort = first month with revenue; starting MRR is the MRR in that month
    SELECT
        customer_id,
        MIN(revenue_month) AS cohort_month
    FROM FINANCE_ANALYTICS.CORE.MONTHLY_REVENUE
    WHERE mrr > 0
    GROUP BY customer_id
),
customer_latest_month AS (
    -- current MRR is the MRR in the customer's latest recorded month (0 if churned)
    SELECT
        customer_id,
        MAX(revenue_month) AS latest_month
    FROM FINANCE_ANALYTICS.CORE.MONTHLY_REVENUE
    GROUP BY customer_id
)
SELECT
    f.cohort_month,
    COUNT(f.customer_id) AS cohort_size,
    SUM(first_rev.mrr) AS cohort_starting_mrr,
    SUM(latest_rev.mrr) AS cohort_current_mrr,
    ROUND(
        SUM(latest_rev.mrr) / NULLIF(SUM(first_rev.mrr), 0) * 100,
        2
    ) AS nrr_pct
FROM customer_first_month f
JOIN FINANCE_ANALYTICS.CORE.MONTHLY_REVENUE first_rev
    ON first_rev.customer_id = f.customer_id
   AND first_rev.revenue_month = f.cohort_month
JOIN customer_latest_month l
    ON l.customer_id = f.customer_id
JOIN FINANCE_ANALYTICS.CORE.MONTHLY_REVENUE latest_rev
    ON latest_rev.customer_id = l.customer_id
   AND latest_rev.revenue_month = l.latest_month
GROUP BY f.cohort_month
ORDER BY f.cohort_month
"""

CHURN_RATE_SQL = """
WITH active_customers AS (
    SELECT
        revenue_month,
        customer_id,
        mrr,
        LAG(mrr) OVER (
            PARTITION BY customer_id
            ORDER BY revenue_month
        ) AS prior_mrr
    FROM FINANCE_ANALYTICS.CORE.MONTHLY_REVENUE
),
churn_flags AS (
    SELECT
        revenue_month,
        customer_id,
        mrr,
        prior_mrr,
        CASE
            WHEN prior_mrr > 0 AND mrr = 0 THEN 1
            ELSE 0
        END AS churned
    FROM active_customers
    WHERE prior_mrr IS NOT NULL
)
SELECT
    revenue_month,
    COUNT(customer_id) AS customers_at_risk,
    SUM(churned) AS churned_customers,
    ROUND(
        SUM(churned) / NULLIF(COUNT(customer_id), 0) * 100,
        2
    ) AS churn_rate_pct
FROM churn_flags
GROUP BY revenue_month
ORDER BY revenue_month
"""

ARR_BY_PLAN_TIER_SQL = """
SELECT
    c.plan_tier,
    SUM(s.annual_contract_value) AS arr
FROM FINANCE_ANALYTICS.CORE.SUBSCRIPTIONS s
INNER JOIN FINANCE_ANALYTICS.CORE.CUSTOMERS c
    ON s.customer_id = c.customer_id
WHERE s.status = 'active'
GROUP BY c.plan_tier
ORDER BY arr DESC
"""


def init_session_state() -> None:
    """Initialize session state keys used by the app."""
    if SESSION_LAST_QUESTION not in st.session_state:
        st.session_state[SESSION_LAST_QUESTION] = None
    if SESSION_LAST_RESULT not in st.session_state:
        st.session_state[SESSION_LAST_RESULT] = None
    if SESSION_WORKFLOW_METRICS not in st.session_state:
        st.session_state[SESSION_WORKFLOW_METRICS] = None
    if SESSION_WORKFLOW_NARRATIVE not in st.session_state:
        st.session_state[SESSION_WORKFLOW_NARRATIVE] = None


def run_sql(sql: str) -> pd.DataFrame:
    """Execute SQL against Snowflake and return a pandas DataFrame."""
    df = session.sql(sql).to_pandas()
    for col in df.columns:
        if df[col].dtype == object:
            has_decimal = df[col].map(
                lambda value: isinstance(value, Decimal) if pd.notna(value) else False
            ).any()
            if has_decimal:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    date_column_names = {"cohort_month", "revenue_month", "start_month"}
    for col in df.columns:
        col_name = str(col).lower()
        if col_name.endswith("_month") or col_name in date_column_names:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def call_cortex_analyst(question: str) -> dict[str, Any]:
    """Send a natural-language question to Cortex Analyst via _snowflake."""
    request_body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": question}],
            }
        ],
        "semantic_model_file": SEMANTIC_MODEL_FILE,
    }
    resp = _snowflake.send_snow_api_request(
        "POST",
        CORTEX_ANALYST_API_ENDPOINT,
        {},
        {},
        request_body,
        {},
        API_TIMEOUT_MS,
    )
    result = json.loads(resp["content"])
    if resp["status"] >= 400:
        detail = result.get("message", resp["content"])
        raise RuntimeError(
            f"Cortex Analyst request failed ({resp['status']}): {detail}"
        )
    return result


def extract_sql_from_analyst_response(response: dict[str, Any]) -> str | None:
    """Return generated SQL from a Cortex Analyst response, if present."""
    content = response.get("message", {}).get("content", [])
    for block in content:
        if block.get("type") == "sql":
            statement = block.get("statement")
            if statement:
                return str(statement).strip()
    return None


def format_analyst_fallback_message(response: dict[str, Any]) -> str:
    """Build a friendly message when Cortex Analyst cannot return SQL."""
    parts: list[str] = []
    content = response.get("message", {}).get("content", [])

    for block in content:
        content_type = block.get("type")
        if content_type == "text" and block.get("text"):
            parts.append(str(block["text"]))
        elif content_type in {"suggestion", "suggestions"}:
            suggestions = block.get("suggestions")
            if suggestions:
                if isinstance(suggestions, list):
                    suggestion_text = "\n".join(f"- {item}" for item in suggestions)
                else:
                    suggestion_text = str(suggestions)
                parts.append(f"Try one of these questions instead:\n{suggestion_text}")

    if parts:
        return "\n\n".join(parts)

    return (
        "I couldn't generate a SQL query for that question. "
        "Try asking about ARR, MRR, churn, revenue trends, or customer segments."
    )


def handle_question_submit(question: str) -> None:
    """Send the question to Cortex Analyst, run SQL, and store results."""
    st.session_state[SESSION_LAST_QUESTION] = question

    try:
        with st.spinner("Asking Cortex Analyst..."):
            analyst_response = call_cortex_analyst(question)

        sql = extract_sql_from_analyst_response(analyst_response)
        if sql is None:
            st.session_state[SESSION_LAST_RESULT] = format_analyst_fallback_message(
                analyst_response
            )
            return

        with st.spinner("Running query..."):
            result_df = run_sql(sql)

        st.session_state[SESSION_LAST_RESULT] = result_df

    except Exception as exc:
        st.session_state[SESSION_LAST_RESULT] = (
            f"Something went wrong while processing your question: {exc}"
        )


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading ARR trend...")
def fetch_arr_trend() -> pd.DataFrame:
    """Fetch monthly ARR trend from active subscriptions."""
    return run_sql(ARR_TREND_SQL)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading NRR by cohort...")
def fetch_nrr_by_cohort() -> pd.DataFrame:
    """Fetch net revenue retention by signup cohort."""
    return run_sql(NRR_BY_COHORT_SQL)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading churn rate...")
def fetch_churn_rate() -> pd.DataFrame:
    """Fetch monthly customer churn rate."""
    return run_sql(CHURN_RATE_SQL)


def render_ask_question_tab() -> None:
    """Render the natural-language question interface."""
    st.subheader("Ask a Question")
    st.caption(
        "Ask a question about ARR, MRR, churn, or revenue movement in plain English."
    )

    question = st.text_input(
        "Your question",
        placeholder="e.g. What was total MRR last month?",
        key="question_input",
    )
    submitted = st.button("Submit", type="primary", key="submit_question")

    if submitted and question.strip():
        handle_question_submit(question.strip())

    st.divider()
    st.markdown("**Results**")

    last_question: str | None = st.session_state[SESSION_LAST_QUESTION]
    last_result: Any = st.session_state[SESSION_LAST_RESULT]

    if last_question is None:
        st.info("Submit a question to see results here.")
        return

    st.markdown(f"**Last question:** {last_question}")

    if last_result is None:
        st.info("No result available yet.")
    elif isinstance(last_result, pd.DataFrame):
        st.dataframe(last_result, use_container_width=True)
    else:
        st.warning(last_result)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of the dataframe with lowercase column names."""
    normalized = df.copy()
    normalized.columns = [str(col).lower() for col in normalized.columns]
    return normalized


def render_arr_trend_chart() -> None:
    """Render ARR over time from active subscriptions."""
    st.subheader("ARR Trend")
    try:
        df = _normalize_columns(fetch_arr_trend())
        if df.empty:
            st.info("No active subscription data available.")
            return

        fig = px.line(
            df,
            x="start_month",
            y="total_arr",
            title="ARR Trend by Subscription Start Month",
            labels={
                "start_month": "Subscription Start Month",
                "total_arr": "Total ARR ($)",
            },
            markers=True,
        )
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.error(f"Unable to load ARR trend: {exc}")


def render_nrr_by_cohort_chart() -> None:
    """Render net revenue retention by signup cohort."""
    st.subheader("NRR by Cohort")
    try:
        df = _normalize_columns(fetch_nrr_by_cohort())
        if df.empty:
            st.info("No cohort data available.")
            return

        fig = px.bar(
            df,
            x="cohort_month",
            y="nrr_pct",
            title="Net Revenue Retention by Cohort",
            labels={
                "cohort_month": "Cohort Month",
                "nrr_pct": "NRR (%)",
            },
        )
        fig.add_hline(
            y=100,
            line_dash="dash",
            line_color="gray",
            annotation_text="100% break-even",
            annotation_position="top right",
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.error(f"Unable to load NRR by cohort: {exc}")


def render_churn_rate_chart() -> None:
    """Render monthly customer churn rate."""
    st.subheader("Churn Rate")
    try:
        df = _normalize_columns(fetch_churn_rate())
        if df.empty:
            st.info("No churn data available.")
            return

        fig = px.line(
            df,
            x="revenue_month",
            y="churn_rate_pct",
            title="Monthly Customer Churn Rate",
            labels={
                "revenue_month": "Revenue Month",
                "churn_rate_pct": "Churn Rate (%)",
            },
            markers=True,
        )
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.error(f"Unable to load churn rate: {exc}")


def render_dashboards_tab() -> None:
    """Render executive dashboard charts."""
    st.subheader("Dashboards")
    st.caption("Executive views for ARR, retention, and churn.")

    render_arr_trend_chart()
    st.divider()
    render_nrr_by_cohort_chart()
    st.divider()
    render_churn_rate_chart()


def compute_quarterly_revenue_metrics() -> dict[str, Any]:
    """Run workflow SQL queries and compute deterministic KPIs in Python."""
    arr_by_tier_df = _normalize_columns(run_sql(ARR_BY_PLAN_TIER_SQL))
    nrr_df = _normalize_columns(run_sql(NRR_BY_COHORT_SQL))
    arr_trend_df = _normalize_columns(run_sql(ARR_TREND_SQL))

    if arr_by_tier_df.empty:
        raise ValueError("No active subscription data found for ARR by plan tier.")

    arr_by_tier = {
        str(row["plan_tier"]): float(row["arr"])
        for _, row in arr_by_tier_df.iterrows()
    }
    total_arr = float(sum(arr_by_tier.values()))

    cohort_starting_mrr_total = (
        float(nrr_df["cohort_starting_mrr"].sum()) if not nrr_df.empty else 0.0
    )
    cohort_current_mrr_total = (
        float(nrr_df["cohort_current_mrr"].sum()) if not nrr_df.empty else 0.0
    )
    weighted_nrr_pct = (
        (cohort_current_mrr_total / cohort_starting_mrr_total * 100)
        if cohort_starting_mrr_total
        else 0.0
    )

    top_3_tiers: list[dict[str, Any]] = []
    sorted_tiers = sorted(arr_by_tier.items(), key=lambda item: item[1], reverse=True)
    top_tier_arr = sorted_tiers[0][1] if sorted_tiers else 0.0
    non_top_tier_combined_arr = total_arr - top_tier_arr
    non_top_tier_combined_pct = (
        (non_top_tier_combined_arr / total_arr * 100) if total_arr else 0.0
    )

    for tier, tier_arr in sorted_tiers[:3]:
        contribution_pct = (tier_arr / total_arr * 100) if total_arr else 0.0
        top_3_tiers.append(
            {
                "plan_tier": tier,
                "arr": tier_arr,
                "contribution_pct": contribution_pct,
            }
        )

    arr_trend_points: list[dict[str, Any]] = []
    if not arr_trend_df.empty:
        trend_sorted = arr_trend_df.sort_values("start_month")
        for _, row in trend_sorted.iterrows():
            arr_trend_points.append(
                {
                    "start_month": row["start_month"].strftime("%Y-%m"),
                    "total_arr": float(row["total_arr"]),
                }
            )

    newest_cohort_arr = arr_trend_points[-1]["total_arr"] if arr_trend_points else total_arr
    prior_cohort_arr = (
        arr_trend_points[-2]["total_arr"] if len(arr_trend_points) > 1 else newest_cohort_arr
    )
    cohort_change_pct = (
        ((newest_cohort_arr - prior_cohort_arr) / prior_cohort_arr * 100)
        if prior_cohort_arr
        else 0.0
    )

    return {
        "total_arr": total_arr,
        "arr_by_tier": arr_by_tier,
        "non_top_tier_combined_arr": non_top_tier_combined_arr,
        "non_top_tier_combined_pct": non_top_tier_combined_pct,
        "weighted_nrr_pct": weighted_nrr_pct,
        "top_3_tiers": top_3_tiers,
        "arr_trend_points": arr_trend_points,
        "newest_cohort_arr": newest_cohort_arr,
        "cohort_change_pct": cohort_change_pct,
    }


def format_metrics_for_prompt(metrics: dict[str, Any]) -> str:
    """Format pre-computed workflow metrics as a text block for Cortex COMPLETE."""
    lines = [
        f"Total ARR: ${metrics['total_arr']:,.2f}",
        "",
        "ARR by plan tier:",
    ]
    for tier, tier_arr in sorted(
        metrics["arr_by_tier"].items(), key=lambda item: item[1], reverse=True
    ):
        contribution = (tier_arr / metrics["total_arr"] * 100) if metrics["total_arr"] else 0.0
        lines.append(f"- {tier}: ${tier_arr:,.2f} ({contribution:.1f}% of total ARR)")

    lines.append(
        "All tiers excluding the top tier, combined: "
        f"${metrics['non_top_tier_combined_arr']:,.2f} "
        f"({metrics['non_top_tier_combined_pct']:.1f}% of total ARR)"
    )

    lines.extend(
        [
            "",
            f"Weighted NRR (by cohort starting MRR): {metrics['weighted_nrr_pct']:.2f}%",
            "",
            "Top 3 plan tiers by ARR contribution:",
        ]
    )
    for tier_info in metrics["top_3_tiers"]:
        lines.append(
            f"- {tier_info['plan_tier']}: ${tier_info['arr']:,.2f} "
            f"({tier_info['contribution_pct']:.1f}% of total ARR)"
        )

    lines.extend(["", "New ARR booked by subscription start month:"])
    for point in metrics["arr_trend_points"]:
        lines.append(f"- {point['start_month']}: ${point['total_arr']:,.2f}")

    lines.extend(
        [
            "",
            f"Newest start-month cohort ARR: ${metrics['newest_cohort_arr']:,.2f}",
            f"Change vs prior start-month cohort: {metrics['cohort_change_pct']:.2f}%",
        ]
    )
    return "\n".join(lines)


def build_quarterly_summary_prompt(metrics_text: str) -> str:
    """Build a structured Cortex COMPLETE prompt using only pre-computed metrics."""
    return f"""Context:
You are a finance analyst briefing a CFO on quarterly revenue performance.

Instructions:
Write a 3-paragraph executive summary using ONLY the numbers provided below.
Use only the figures provided below. Never add, subtract, or otherwise derive new numbers.
Paragraph 1: headline ARR and recent new-booking activity.
Paragraph 2: composition by plan tier and concentration.
Paragraph 3: one risk and one opportunity grounded in the data.
Do not compute new figures, estimate missing values, or invent metrics.

Few-shot example:
Input numbers:
Total ARR: $1,200,000.00
Weighted NRR (by cohort starting MRR): 108.50%
Top tier: Enterprise at 55.0% of total ARR
Newest start-month cohort ARR: $310,000.00
Change vs prior start-month cohort: 4.20%

Good summary:
Total ARR stands at $1,200,000.00. The newest start-month cohort booked $310,000.00 in new ARR, up 4.20% versus the prior start-month cohort, indicating steady new-booking activity rather than a running ARR total.

Revenue is concentrated in Enterprise, which contributes 55.0% of total ARR, indicating strong performance in the highest-value segment while other tiers provide diversification.

The main risk is tier concentration if Enterprise growth slows, while the opportunity is to lift weighted NRR above 108.50% by expanding within existing cohorts.

Output format:
Exactly 3 paragraphs. No markdown, bullets, or headings.

Provided numbers (use these only):
{metrics_text}
"""


def _escape_sql_string(value: str) -> str:
    """Escape single quotes for safe inclusion in a SQL string literal."""
    return value.replace("'", "''")


def generate_quarterly_narrative(metrics: dict[str, Any]) -> str:
    """Call Cortex COMPLETE to narrate pre-computed quarterly revenue metrics."""
    prompt = build_quarterly_summary_prompt(format_metrics_for_prompt(metrics))
    result_df = session.sql(
        "SELECT SNOWFLAKE.CORTEX.COMPLETE(?, ?) AS summary",
        params=["mistral-large2", prompt],
    ).to_pandas()
    return str(result_df.iloc[0, 0]).strip()

def run_quarterly_revenue_workflow() -> tuple[dict[str, Any], str]:
    """Execute the quarterly revenue summary agentic workflow end to end."""
    metrics = compute_quarterly_revenue_metrics()
    narrative = generate_quarterly_narrative(metrics)
    return metrics, narrative


def render_workflow_tab() -> None:
    """Render the agentic quarterly revenue summary workflow.

    This tab encodes a repeatable finance process: pull ARR and NRR data from
    Snowflake, compute KPIs deterministically in Python, then pass only those
    figures to Cortex COMPLETE for executive narrative generation.
    """
    st.subheader("Workflow")
    st.caption(
        "Run a repeatable quarterly revenue briefing workflow with deterministic "
        "metrics and AI-generated narrative."
    )

    if st.button(
        "Generate Quarterly Revenue Summary",
        type="primary",
        key="generate_quarterly_summary",
    ):
        try:
            with st.spinner("Running quarterly revenue workflow..."):
                metrics, narrative = run_quarterly_revenue_workflow()
            st.session_state[SESSION_WORKFLOW_METRICS] = metrics
            st.session_state[SESSION_WORKFLOW_NARRATIVE] = narrative
        except Exception as exc:
            st.error(f"Workflow failed: {exc}")

    metrics: dict[str, Any] | None = st.session_state[SESSION_WORKFLOW_METRICS]
    narrative: str | None = st.session_state[SESSION_WORKFLOW_NARRATIVE]

    if metrics is None:
        st.info("Click the button above to generate a quarterly revenue summary.")
        return

    metric_cols = st.columns(4)
    metric_cols[0].metric("Total ARR", f"${metrics['total_arr']:,.0f}")
    metric_cols[1].metric("Weighted NRR", f"{metrics['weighted_nrr_pct']:.1f}%")
    metric_cols[2].metric(
        "Newest Cohort ARR",
        f"${metrics['newest_cohort_arr']:,.0f}",
        f"{metrics['cohort_change_pct']:+.1f}% vs prior start-month",
    )
    top_tier = metrics["top_3_tiers"][0] if metrics["top_3_tiers"] else None
    metric_cols[3].metric(
        "Top Tier Share",
        f"{top_tier['contribution_pct']:.1f}%" if top_tier else "N/A",
        top_tier["plan_tier"] if top_tier else None,
    )

    st.divider()
    st.markdown("**Executive Summary**")
    if narrative:
        st.markdown(narrative.replace("$", "\\$"))
    else:
        st.info("No narrative generated yet.")


def main() -> None:
    """Run the Finance Analytics Streamlit app."""
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_session_state()

    st.title(APP_TITLE)

    ask_tab, dashboards_tab, workflow_tab = st.tabs(
        ["Ask a Question", "Dashboards", "Workflow"]
    )

    with ask_tab:
        render_ask_question_tab()

    with dashboards_tab:
        render_dashboards_tab()

    with workflow_tab:
        render_workflow_tab()


if __name__ == "__main__":
    main()
