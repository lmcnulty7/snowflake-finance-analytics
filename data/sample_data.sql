-- Demo data for the AI-Powered Finance Analytics App: a synthetic 10-customer SaaS dataset.
-- Exported from FINANCE_ANALYTICS.CORE on 2026-10-03 (table DDL via GET_DDL, rows via SELECT).
-- Run in a Snowsight worksheet or SnowSQL; it recreates the three tables the app reads.

CREATE DATABASE IF NOT EXISTS FINANCE_ANALYTICS;
CREATE SCHEMA IF NOT EXISTS FINANCE_ANALYTICS.CORE;
USE SCHEMA FINANCE_ANALYTICS.CORE;

-- CUSTOMERS
create or replace TABLE CUSTOMERS (
	CUSTOMER_ID VARCHAR(36) NOT NULL,
	COMPANY_NAME VARCHAR(225),
	INDUSTRY VARCHAR(100),
	SIGNUP_DATE DATE,
	PLAN_TIER VARCHAR(50),
	primary key (CUSTOMER_ID)
);

INSERT INTO CUSTOMERS (CUSTOMER_ID, COMPANY_NAME, INDUSTRY, SIGNUP_DATE, PLAN_TIER) VALUES
    ('c001', 'Acme Corp', 'Technology', '2023-01-15', 'Enterprise'),
    ('c002', 'Blue Ridge Co', 'Healthcare', '2023-02-01', 'Growth'),
    ('c003', 'Cascade Inc', 'Finance', '2023-03-10', 'Enterprise'),
    ('c004', 'Delta Systems', 'Retail', '2023-04-05', 'Starter'),
    ('c005', 'Echo Analytics', 'Technology', '2023-05-20', 'Growth'),
    ('c006', 'Frontier Labs', 'Healthcare', '2023-06-01', 'Enterprise'),
    ('c007', 'Global Reach', 'Finance', '2023-07-15', 'Growth'),
    ('c008', 'Harbor Tech', 'Retail', '2023-08-01', 'Starter'),
    ('c009', 'Iris Software', 'Technology', '2023-09-10', 'Enterprise'),
    ('c010', 'Jade Ventures', 'Healthcare', '2023-10-01', 'Growth');

-- SUBSCRIPTIONS
create or replace TABLE SUBSCRIPTIONS (
	SUBSCRIPTION_ID VARCHAR(36) NOT NULL,
	CUSTOMER_ID VARCHAR(36),
	START_DATE DATE,
	END_DATE DATE,
	ANNUAL_CONTRACT_VALUE NUMBER(12,2),
	STATUS VARCHAR(20),
	primary key (SUBSCRIPTION_ID)
);

INSERT INTO SUBSCRIPTIONS (SUBSCRIPTION_ID, CUSTOMER_ID, START_DATE, END_DATE, ANNUAL_CONTRACT_VALUE, STATUS) VALUES
    ('s001', 'c001', '2023-01-15', '2024-01-15', 120000.00, 'active'),
    ('s002', 'c002', '2023-02-01', '2024-02-01', 48000.00, 'active'),
    ('s003', 'c003', '2023-03-10', '2024-03-10', 96000.00, 'active'),
    ('s004', 'c004', '2023-04-05', '2024-04-05', 12000.00, 'churned'),
    ('s005', 'c005', '2023-05-20', '2024-05-20', 48000.00, 'active'),
    ('s006', 'c006', '2023-06-01', '2024-06-01', 120000.00, 'active'),
    ('s007', 'c007', '2023-07-15', '2024-07-15', 48000.00, 'active'),
    ('s008', 'c008', '2023-08-01', '2024-08-01', 12000.00, 'churned'),
    ('s009', 'c009', '2023-09-10', '2024-09-10', 96000.00, 'active'),
    ('s010', 'c010', '2023-10-01', '2024-10-01', 48000.00, 'active');

-- MONTHLY_REVENUE
create or replace TABLE MONTHLY_REVENUE (
	CUSTOMER_ID VARCHAR(36),
	REVENUE_MONTH DATE,
	MRR NUMBER(12,2),
	REVENUE_TYPE VARCHAR(50)
);

INSERT INTO MONTHLY_REVENUE (CUSTOMER_ID, REVENUE_MONTH, MRR, REVENUE_TYPE) VALUES
    ('c001', '2023-01-01', 10000.00, 'new'),
    ('c001', '2023-02-01', 10000.00, 'renewal'),
    ('c001', '2023-03-01', 11000.00, 'expansion'),
    ('c002', '2023-02-01', 4000.00, 'new'),
    ('c002', '2023-03-01', 4000.00, 'renewal'),
    ('c002', '2023-04-01', 3500.00, 'contraction'),
    ('c003', '2023-03-01', 8000.00, 'new'),
    ('c003', '2023-04-01', 8000.00, 'renewal'),
    ('c003', '2023-05-01', 9000.00, 'expansion'),
    ('c004', '2023-04-01', 1000.00, 'new'),
    ('c004', '2023-05-01', 1000.00, 'renewal'),
    ('c004', '2023-06-01', 0.00, 'churn'),
    ('c005', '2023-05-01', 4000.00, 'new'),
    ('c005', '2023-06-01', 4000.00, 'renewal'),
    ('c005', '2023-07-01', 4500.00, 'expansion'),
    ('c006', '2023-06-01', 10000.00, 'new'),
    ('c006', '2023-07-01', 10000.00, 'renewal'),
    ('c006', '2023-08-01', 10000.00, 'renewal'),
    ('c007', '2023-07-01', 4000.00, 'new'),
    ('c007', '2023-08-01', 4000.00, 'renewal'),
    ('c007', '2023-09-01', 4200.00, 'expansion'),
    ('c008', '2023-08-01', 1000.00, 'new'),
    ('c008', '2023-09-01', 0.00, 'churn'),
    ('c009', '2023-09-01', 8000.00, 'new'),
    ('c009', '2023-10-01', 8000.00, 'renewal'),
    ('c009', '2023-11-01', 8500.00, 'expansion'),
    ('c010', '2023-10-01', 4000.00, 'new'),
    ('c010', '2023-11-01', 4000.00, 'renewal'),
    ('c010', '2023-12-01', 4000.00, 'renewal');
