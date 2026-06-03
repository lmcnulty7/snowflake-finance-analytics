"""Finance Analytics Streamlit application."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
import streamlit as st
from streamlit.connections import SnowflakeConnection

APP_TITLE = "Finance Analytics"
SESSION_LAST_QUESTION = "last_question"
SESSION_LAST_RESULT = "last_result"
CACHE_TTL = timedelta(minutes=10)

ARR_TREND_SQL = """
SELECT
    revenue_month,
    SUM(mrr) * 12 AS arr
FROM finance_analytics.core.monthly_revenue
WHERE mrr > 0
GROUP BY revenue_month
ORDER BY revenue_month
"""

NRR_BY_COHORT_SQL = """
WITH customer_first_month AS (
    SELECT
        customer_id,
        MIN(revenue_month) AS cohort_month,
        SUM(mrr) AS first_mrr
    FROM finance_analytics.core.monthly_revenue
    WHERE mrr > 0
    GROUP BY customer_id
),
customer_latest_month AS (
    SELECT
        customer_id,
        MAX(revenue_month) AS latest_month,
        SUM(mrr) AS latest_mrr
    FROM finance_analytics.core.monthly_revenue
    GROUP BY customer_id
)
SELECT
    f.cohort_month,
    COUNT(f.customer_id) AS cohort_size,
    SUM(f.first_mrr) AS cohort_starting_mrr,
    SUM(l.latest_mrr) AS cohort_current_mrr,
    ROUND(
        SUM(l.latest_mrr) / NULLIF(SUM(f.first_mrr), 0) * 100,
        2
    ) AS nrr_pct
FROM customer_first_month f
JOIN customer_latest_month l ON f.customer_id = l.customer_id
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
    FROM finance_analytics.core.monthly_revenue
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


def init_session_state() -> None:
    """Initialize session state keys used by the app."""
    if SESSION_LAST_QUESTION not in st.session_state:
        st.session_state[SESSION_LAST_QUESTION] = None
    if SESSION_LAST_RESULT not in st.session_state:
        st.session_state[SESSION_LAST_RESULT] = None


def get_snowflake_connection() -> SnowflakeConnection:
    """Return the Snowflake connection configured in secrets or connections.toml."""
    return st.connection("snowflake", type="snowflake")


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading ARR trend...")
def fetch_arr_trend() -> pd.DataFrame:
    """Fetch monthly ARR trend derived from MRR."""
    conn = get_snowflake_connection()
    return conn.query(ARR_TREND_SQL, ttl=0)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading NRR by cohort...")
def fetch_nrr_by_cohort() -> pd.DataFrame:
    """Fetch net revenue retention by signup cohort."""
    conn = get_snowflake_connection()
    return conn.query(NRR_BY_COHORT_SQL, ttl=0)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading churn rate...")
def fetch_churn_rate() -> pd.DataFrame:
    """Fetch monthly customer churn rate."""
    conn = get_snowflake_connection()
    return conn.query(CHURN_RATE_SQL, ttl=0)


def handle_question_submit(question: str) -> None:
    """Store the submitted question and a placeholder result in session state."""
    st.session_state[SESSION_LAST_QUESTION] = question
    st.session_state[SESSION_LAST_RESULT] = (
        "Results will appear here once Cortex Analyst is connected."
    )


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
        st.write(last_result)


def render_dashboard_section(title: str) -> None:
    """Render a dashboard section with a placeholder chart message."""
    st.subheader(title)
    st.info("Chart coming soon")


def render_dashboards_tab() -> None:
    """Render dashboard placeholders for future chart integration."""
    st.subheader("Dashboards")
    st.caption("Executive views for ARR, retention, and churn.")

    render_dashboard_section("ARR Trend")
    render_dashboard_section("NRR by Cohort")
    render_dashboard_section("Churn Rate")


def main() -> None:
    """Run the Finance Analytics Streamlit app."""
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_session_state()

    st.title(APP_TITLE)

    ask_tab, dashboards_tab = st.tabs(["Ask a Question", "Dashboards"])

    with ask_tab:
        render_ask_question_tab()

    with dashboards_tab:
        render_dashboards_tab()


if __name__ == "__main__":
    main()
