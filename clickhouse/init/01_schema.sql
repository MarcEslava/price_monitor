-- Analytical store for competitor price history.
-- Runs once on first container init (mounted into /docker-entrypoint-initdb.d).
-- The load task in the Airflow DAG also runs CREATE TABLE IF NOT EXISTS, so the
-- schema is self-healing even if this init is skipped.

CREATE DATABASE IF NOT EXISTS price_monitor;

CREATE TABLE IF NOT EXISTS price_monitor.price_history
(
    scraped_at DateTime,                       -- when this run observed the price
    run_id     String,                         -- Airflow DAG run id
    site       LowCardinality(String),         -- competitor id: primor / farmavazquez / atida
    sku        String,
    url        String,
    name       String,
    price      Nullable(Float64),              -- current selling price (EUR)
    currency   LowCardinality(String),
    in_stock   UInt8
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(scraped_at)
-- ordered so "latest price per product" and per-product time series are cheap
ORDER BY (site, url, scraped_at);
