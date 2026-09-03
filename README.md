# price_monitor

A Scrapy project for tracking competitor prices and alerting on changes.

## Setup

```bash
pip install -r requirements.txt
```

## Project layout

```
price_monitor/
  scrapy.cfg
  requirements.txt
  price_monitor/
    items.py                        # ProductItem: shared schema every spider yields
    pipelines.py                    # stores history in SQLite, detects price changes
    settings.py                     # throttling, robots.txt, pipeline + Playwright config
    spiders/
      books_example.py              # working example (books.toscrape.com)
      _template_competitor.py       # copy this for each new competitor site
      competitor_primor.py          # primor.eu (server-rendered, plain Scrapy)
      competitor_farmavazquez.py    # farmavazquez.com (server-rendered, plain Scrapy)
      competitor_atida.py           # atida.com (client-rendered via Algolia, needs Playwright)
```

## The competitor spiders (search-driven)

The pipeline is **search-driven**: Airflow (Price Monitor ETL) pulls the product
list from Zoho CRM and hands each spider a `products` JSON — `[{"ean","name","brand"}, …]`.
Each spider then looks those products up on its competitor and returns prices
**keyed back to your EAN** (`input_ean`), with a `match_score` confidence so the
pricing side can auto-accept high scores and route low ones to review. All
connections/credentials live in Airflow; the container is a stateless scraper
triggered per ETL run via Scrapyd `schedule.json`.

Two modes, depending on what each site permits (see `_search.py` + `_template_competitor.py`):

- **Search-driven** — `competitor_atida.py` (Algolia API; atida is behind a
  captcha/WAF so the browser approach is dead — we query the JSON API the
  frontend uses) and `competitor_farmavazquez.py` (PrestaShop `search_query`).
  For each product they search and return the best match tagged with its EAN.
- **Category-crawl + offline match** — `competitor_primor.py`. primor's
  `robots.txt` disallows search (`/*?q=`), but browsing categories is allowed, so
  this spider crawls the configured `categories` (`?p=N` pagination) and emits
  RAW listings; the Price Monitor ETL matches them to your catalog by name+brand
  using the shared `match_score`.

Trigger examples (what Airflow does):

```bash
# search-driven
curl http://localhost:6800/schedule.json -d project=price_monitor \
  -d spider=competitor_atida \
  --data-urlencode 'products=[{"ean":"8470...","name":"Avene Solar Spray SPF50 200ml","brand":"Avene"}]'
# category-crawl
curl http://localhost:6800/schedule.json -d project=price_monitor \
  -d spider=competitor_primor \
  --data-urlencode 'categories=["https://www.primor.eu/es_es/perfumes-de-mujer"]'
```

Each spider's docstring documents the confirmed selectors / API config, so if a
site changes later you know where to start.

**Before running these against real data**: the `start_urls` in each spider currently point at one example category/search page — replace them with whichever categories or products you actually want to track. Also worth a look: each site's `robots.txt` and Terms of Service, since none of this has been checked for these 3 specific sites yet.

## Running a spider

```bash
scrapy crawl books_example
```

This appends every scraped product to `prices.db` (SQLite) under a
`price_history` table. If a product's price differs from the last time it
was scraped, a row is added to `price_alerts` and to `price_alerts.csv`.

List all spiders:

```bash
scrapy list
```

## Adding a competitor site

1. Copy `spiders/_template_competitor.py` to `spiders/competitor_<name>.py`.
2. Follow the TODOs: set `name`, `allowed_domains`, `start_urls`, and the
   CSS/XPath selectors for the product name, URL, and price.
3. Check the site's `robots.txt` (e.g. `https://sitename.com/robots.txt`)
   and Terms of Service before scraping — some sites explicitly prohibit
   it. `ROBOTSTXT_OBEY = True` in settings.py will make Scrapy respect
   disallowed paths automatically.
4. Run it: `scrapy crawl competitor_<name>`

Each spider yields the same `ProductItem` shape, so all of them flow
through the same price-change pipeline without extra wiring.

## Checking for price changes

```bash
sqlite3 prices.db "SELECT * FROM price_alerts ORDER BY detected_at DESC;"
```

or just open `price_alerts.csv`.

## Running all spiders and getting alerted

A simple runner script to crawl every spider in one go:

```bash
scrapy list | xargs -I {} scrapy crawl {}
```

For actual "alert me" behavior (email/Slack/etc.), the cleanest hook point
is `PriceChangePipeline.process_item` in `pipelines.py` — right where it
already logs `PRICE CHANGE: ...` and writes to the CSV, you can add a call
to send an email, post to Slack, etc.

## Running as a container (Scrapyd) — how the Airflow pipeline pulls prices

For the data pipeline (`C:\dev\pipeline`), this project runs as its own
long-lived **Scrapyd** container rather than being invoked ad-hoc. Airflow
talks to it over HTTP: it triggers crawls, waits for them to finish, and
downloads the scraped items. Nothing about the pipeline needs the Scrapy code
itself — only the running daemon.

```bash
# From this repo:
docker compose up -d --build      # builds the image, starts scrapyd on :6800
```

The container (see `Dockerfile`, `scrapyd.conf`, `docker-entrypoint.sh`,
`docker-compose.yml`):

- runs **Scrapyd** bound to `0.0.0.0:6800`; on startup the entrypoint deploys
  the project into it as an egg (`scrapyd-deploy`),
- bundles chromium via `playwright install --with-deps` so the Playwright-based
  `competitor_atida` spider works inside the container,
- sets `items_dir`, so each finished job's items are stored **and served over
  HTTP** at `/items/<project>/<spider>/<jobid>.jl` — this is what Airflow pulls,
- joins the pipeline's Docker network (external network `pipeline_confluent`)
  so Airflow reaches it at **`http://scrapyd:6800`**.

> **Network name assumption:** `docker-compose.yml` attaches to an external
> network named `pipeline_confluent` (Compose's `<project>_<network>` naming for
> the `confluent` network defined in the pipeline stack under project name
> `pipeline`). If your pipeline stack uses a different project name, edit the
> `networks:` block here to match. Bring the pipeline stack up first so the
> network exists.

### Nicer UI: Gerapy

Scrapyd's built-in page (`:6800`) is monitoring-only and very bare. The compose
stack also starts **Gerapy** — a Django + Vue dashboard — as a separate
container that talks to scrapyd over its **JSON API**:

```
http://localhost:8000     (default login: admin / admin)
```

It uses the author's official image (`germey/gerapy`, pinned by digest in
docker-compose.yml). The image auto-runs init/migrate/initadmin/runserver on
first boot, so there's nothing to build. The scrapyd node is registered as
`scrapyd:6800` inside Gerapy's DB (persisted in the `gerapy_data` volume).

> **Why not ScrapydWeb?** It screen-scrapes Scrapyd's *HTML* jobs page, and
> Scrapyd 1.6 changed that page — so ScrapydWeb 1.4.0 (last released 2019) just
> shows "Oops! Something went wrong". Gerapy uses the stable JSON API instead.

> **Security:** default creds are `admin`/`admin` and it's on the internal
> network — change the password (top-right menu in the UI) and don't expose
> `:8000` publicly as-is.

If the node ever needs re-adding: in the UI go to **Hosts → Create**, name it
anything, IP `scrapyd`, port `6800`, auth off.

### Analytical store: ClickHouse

Price history lives in a **ClickHouse** container (columnar OLAP) — the interim
analytical store until Snowflake. The Airflow DAG's `load` task appends each
run's observations to `price_monitor.price_history`; BI tools (Metabase has a
first-class ClickHouse driver; PowerBI via ODBC) connect to it for trend /
cross-competitor analysis.

- HTTP: `http://localhost:8123` · native TCP: `9000` · reachable on the network as `clickhouse`
- DB/user `price_monitor` (password in `docker-compose.yml` — **change it**, and
  keep the `clickhouse_password` Airflow Variable in sync)
- Schema: `clickhouse/init/01_schema.sql` (also `CREATE TABLE IF NOT EXISTS`'d by
  the DAG, so it's self-healing)

```bash
# quick look
curl "http://localhost:8123/?query=SELECT%20site,count()%20FROM%20price_monitor.price_history%20GROUP%20BY%20site" \
  -H "X-ClickHouse-User: price_monitor" -H "X-ClickHouse-Key: changeme_pm"
```

Migration to Snowflake later is straightforward: the table is plain columnar SQL,
exportable to Parquet for a Snowflake external stage.

Trigger / inspect crawls directly (the Airflow DAG does the same over HTTP):

```bash
curl http://localhost:6800/daemonstatus.json
curl -d project=price_monitor -d spider=competitor_primor http://localhost:6800/schedule.json
curl "http://localhost:6800/listjobs.json?project=price_monitor"
```

The Airflow side lives in the pipeline repo at
`dags/price_monitor_ETL.py`: a TaskFlow DAG that fans out one task per spider
(`crawl_and_pull.expand(...)`), triggers each via `schedule.json`, polls
`listjobs.json`, and writes the pulled items to
`/opt/airflow/data/staging/price_monitor/<run_id>/<spider>.jsonl`. Two Airflow
Variables tune it: `scrapyd_base_url` (default `http://scrapyd:6800`) and
`price_monitor_schedule` (default `0 6 * * *`).

The `airflow_example/` DAG in this repo is now just an illustrative sketch —
`dags/price_monitor_ETL.py` in the pipeline repo is the real, running version.

## Scheduling recurring runs (standalone, without the pipeline)

If you're *not* using the Airflow pipeline, price monitoring still needs a
schedule. Options:

- **cron** (Linux/Mac) or **Task Scheduler** (Windows): run
  `scrapy crawl <spider>` daily/hourly from the `price_monitor/` directory.
- Ask me to set up a recurring scheduled task that runs this crawl and
  reports back with any detected price changes.

## Notes on legality/etiquette

- `ROBOTSTXT_OBEY` is on by default — leave it on unless you've checked
  the site permits scraping.
- `AUTOTHROTTLE` and `DOWNLOAD_DELAY` are enabled to avoid hammering
  competitor servers.
- The `USER_AGENT` in settings.py identifies this bot honestly rather
  than impersonating a browser — update the contact info as needed.
- Scraping competitor pricing for market research is common practice, but
  ToS terms vary by site — worth a quick check per target, and legal
  advice if this becomes business-critical.
