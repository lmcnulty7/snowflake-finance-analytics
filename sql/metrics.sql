-- ARR by customer (active subscriptions only)
SELECT
    c.customer_id,
    c.company_name,
    c.industry,
    c.plan_tier,
    s.annual_contract_value AS arr,
    s.start_date,
    s.end_date,
    s.status
FROM CUSTOMERS c
JOIN SUBSCRIPTIONS s ON c.customer_id = s.customer_id
WHERE s.status = 'active'
ORDER BY s.annual_contract_value DESC;

-- MRR trend with month over month growth
SELECT
    revenue_month,
    SUM(mrr) AS total_mrr,
    SUM(mrr) * 12 AS implied_arr,
    LAG(SUM(mrr)) OVER (ORDER BY revenue_month) AS prior_month_mrr,
    ROUND(
        (SUM(mrr) - LAG(SUM(mrr)) OVER (ORDER BY revenue_month)) 
        / NULLIF(LAG(SUM(mrr)) OVER (ORDER BY revenue_month), 0) * 100, 
        2
    ) AS mom_growth_pct
FROM MONTHLY_REVENUE
WHERE mrr > 0
GROUP BY revenue_month
ORDER BY revenue_month;

-- NRR by cohort month
WITH customer_first_month AS (
    SELECT
        customer_id,
        MIN(revenue_month) AS cohort_month,
        SUM(mrr) AS first_mrr
    FROM MONTHLY_REVENUE
    WHERE mrr > 0
    GROUP BY customer_id
),
customer_latest_month AS (
    SELECT
        customer_id,
        MAX(revenue_month) AS latest_month,
        SUM(mrr) AS latest_mrr
    FROM MONTHLY_REVENUE
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
ORDER BY f.cohort_month;

-- Monthly churn rate
WITH active_customers AS (
    SELECT
        revenue_month,
        customer_id,
        mrr,
        LAG(mrr) OVER (
            PARTITION BY customer_id 
            ORDER BY revenue_month
        ) AS prior_mrr
    FROM MONTHLY_REVENUE
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
ORDER BY revenue_month;