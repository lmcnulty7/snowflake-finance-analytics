"""Finance Analytics Streamlit application."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

APP_TITLE = "Finance Analytics"
SESSION_LAST_QUESTION = "last_question"
SESSION_LAST_RESULT = "last_result"
CACHE_TTL = timedelta(minutes=10)
CORTEX_ANALYST_API_PATH = "/api/v2/cortex/analyst/message"
API_TIMEOUT_SECONDS = 60
SEMANTIC_MODEL_STAGE_PATH = (
    "@FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE/finance_model.yaml"
)

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
    SELECT
        customer_id,
        MIN(revenue_month) AS cohort_month,
        SUM(mrr) AS first_mrr
    FROM FINANCE_ANALYTICS.CORE.MONTHLY_REVENUE
    WHERE mrr > 0
    GROUP BY customer_id
),
customer_latest_month AS (
    SELECT
        customer_id,
        MAX(revenue_month) AS latest_month,
        SUM(mrr) AS latest_mrr
    FROM FINANCE_ANALYTICS.CORE.MONTHLY_REVENUE
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


def init_session_state() -> None:
    """Initialize session state keys used by the app."""
    if SESSION_LAST_QUESTION not in st.session_state:
        st.session_state[SESSION_LAST_QUESTION] = None
    if SESSION_LAST_RESULT not in st.session_state:
        st.session_state[SESSION_LAST_RESULT] = None


def get_snowflake_connection() -> Any:
    """Return the Snowflake connection (automatic in Streamlit in Snowflake)."""
    return st.connection("snowflake")


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading semantic model...")
def load_semantic_model() -> str:
    """Read the Cortex Analyst semantic model YAML from a Snowflake stage."""
    conn = get_snowflake_connection()
    session = conn.session()
    try:
        with session.file.get_stream(SEMANTIC_MODEL_STAGE_PATH) as stream:
            content = stream.read().decode("utf-8")
    except Exception as exc:
        raise FileNotFoundError(
            f"Semantic model not found at {SEMANTIC_MODEL_STAGE_PATH}"
        ) from exc
    if not content.strip():
        raise ValueError(f"Semantic model at {SEMANTIC_MODEL_STAGE_PATH} is empty.")
    return content


def build_cortex_analyst_url(conn: Any) -> str:
    """Build the Cortex Analyst REST API URL for the connected account."""
    host = conn.raw_connection.host
    return f"https://{host}{CORTEX_ANALYST_API_PATH}"


def build_cortex_analyst_headers(conn: Any) -> dict[str, str]:
    """Build authorization headers for the Cortex Analyst REST API."""
    token = conn.raw_connection.rest.token
    return {
        "Authorization": f'Snowflake Token="{token}"',
        "Content-Type": "application/json",
        "X-Snowflake-Authorization-Token-Type": "SESSION",
    }


def call_cortex_analyst(
    question: str,
    semantic_model: str,
    conn: Any,
) -> dict[str, Any]:
    """Send a natural-language question and semantic model to Cortex Analyst."""
    request_body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": question}],
            }
        ],
        "semantic_model": semantic_model,
    }
    response = requests.post(
        build_cortex_analyst_url(conn),
        json=request_body,
        headers=build_cortex_analyst_headers(conn),
        timeout=API_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        try:
            payload = response.json()
            detail = payload.get("message", response.text)
        except json.JSONDecodeError:
            detail = response.text
        raise RuntimeError(
            f"Cortex Analyst request failed ({response.status_code}): {detail}"
        )
    return response.json()


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
        conn = get_snowflake_connection()
        semantic_model = load_semantic_model()

        with st.spinner("Asking Cortex Analyst..."):
            analyst_response = call_cortex_analyst(question, semantic_model, conn)

        sql = extract_sql_from_analyst_response(analyst_response)
        if sql is None:
            st.session_state[SESSION_LAST_RESULT] = format_analyst_fallback_message(
                analyst_response
            )
            return

        with st.spinner("Running query..."):
            result_df = conn.query(sql, ttl=0)

        st.session_state[SESSION_LAST_RESULT] = result_df

    except FileNotFoundError:
        st.session_state[SESSION_LAST_RESULT] = (
            "The semantic model file could not be found on stage. "
            "Check that @FINANCE_ANALYTICS.CORE.STREAMLIT_STAGE/finance_model.yaml exists."
        )
    except requests.RequestException:
        st.session_state[SESSION_LAST_RESULT] = (
            "Unable to reach Cortex Analyst. Check your network connection "
            "and Snowflake credentials, then try again."
        )
    except Exception as exc:
        st.session_state[SESSION_LAST_RESULT] = (
            f"Something went wrong while processing your question: {exc}"
        )


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading ARR trend...")
def fetch_arr_trend() -> pd.DataFrame:
    """Fetch monthly ARR trend from active subscriptions."""
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
