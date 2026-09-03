BOT_NAME = "price_monitor"

SPIDER_MODULES = ["price_monitor.spiders"]
NEWSPIDER_MODULE = "price_monitor.spiders"

# Identify yourself honestly. Some sites block generic/default user agents,
# and impersonating a browser can violate a site's terms of service.
USER_AGENT = "price_monitor (+https://example.com; contact: dev1@ecoceutics.net)"

# Respect robots.txt by default. Turn off only for sites you have explicit
# permission to scrape, and check the site's Terms of Service first.
ROBOTSTXT_OBEY = True

# Be polite: throttle requests so you don't hammer competitor servers.
DOWNLOAD_DELAY = 1
RANDOMIZE_DOWNLOAD_DELAY = True
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# Detection/alerting now lives in the Airflow DAG (price_monitor_ETL), which
# compares runs and emails alerts. The spiders are extract-only: Scrapyd stores
# each job's items to its items_dir (served over HTTP) and Airflow pulls them.
# The old PriceChangePipeline (SQLite + CSV) is left in pipelines.py for
# reference but is no longer enabled. Re-add it here only if you want the
# container to do standalone detection again.
ITEM_PIPELINES = {}

# Where price history / alerts are stored (relative to where you run scrapy)
PRICE_DB_PATH = "prices.db"
ALERTS_CSV_PATH = "price_alerts.csv"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"

LOG_LEVEL = "INFO"

# No spider needs a real browser anymore: the sites that render content
# client-side (atida) are scraped via their JSON/search API instead, so the
# scrapy-playwright download handler has been removed. All spiders are plain
# HTTP now. (TWISTED_REACTOR above stays as the asyncio reactor, which is
# Scrapy's default and what async spider code like competitor_atida.start uses.)
