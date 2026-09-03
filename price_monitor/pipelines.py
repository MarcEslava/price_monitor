"""
Storage + price-change-detection pipeline.

Every scraped item is appended to a SQLite `price_history` table (so you keep
a full history, not just the latest snapshot). If a previous price exists for
the same (site, url) and it differs from the new one, a row is written to
`price_alerts` and appended to alerts.csv for easy scanning / hooking up to
an email or Slack notifier later.
"""
import csv
import os
import sqlite3
from datetime import datetime, timezone

from itemadapter import ItemAdapter


class PriceChangePipeline:
    def __init__(self, db_path, alerts_csv_path):
        self.db_path = db_path
        self.alerts_csv_path = alerts_csv_path
        self.conn = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            db_path=crawler.settings.get("PRICE_DB_PATH", "prices.db"),
            alerts_csv_path=crawler.settings.get("ALERTS_CSV_PATH", "price_alerts.csv"),
        )

    def open_spider(self, spider):
        self.conn = sqlite3.connect(self.db_path)
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site TEXT NOT NULL,
                url TEXT NOT NULL,
                name TEXT,
                price REAL,
                currency TEXT,
                in_stock INTEGER,
                scraped_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site TEXT NOT NULL,
                url TEXT NOT NULL,
                name TEXT,
                old_price REAL,
                new_price REAL,
                change_pct REAL,
                detected_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_site_url ON price_history(site, url, scraped_at)"
        )
        self.conn.commit()

        if not os.path.exists(self.alerts_csv_path):
            with open(self.alerts_csv_path, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["detected_at", "site", "name", "old_price", "new_price", "change_pct", "url"]
                )

    def close_spider(self, spider):
        if self.conn:
            self.conn.close()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        site = adapter.get("site") or spider.name
        url = adapter.get("url")
        name = adapter.get("name")
        price = adapter.get("price")
        currency = adapter.get("currency")
        in_stock = adapter.get("in_stock")
        now = datetime.now(timezone.utc).isoformat()

        cur = self.conn.cursor()

        # Look up the most recent previously recorded price for this product
        cur.execute(
            """
            SELECT price FROM price_history
            WHERE site = ? AND url = ?
            ORDER BY scraped_at DESC, id DESC
            LIMIT 1
            """,
            (site, url),
        )
        row = cur.fetchone()
        previous_price = row[0] if row else None

        # Insert the new observation into history
        cur.execute(
            """
            INSERT INTO price_history (site, url, name, price, currency, in_stock, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (site, url, name, price, currency, int(bool(in_stock)) if in_stock is not None else None, now),
        )

        if previous_price is not None and price is not None and previous_price != price:
            change_pct = ((price - previous_price) / previous_price * 100) if previous_price else None
            cur.execute(
                """
                INSERT INTO price_alerts (site, url, name, old_price, new_price, change_pct, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (site, url, name, previous_price, price, change_pct, now),
            )
            with open(self.alerts_csv_path, "a", newline="") as f:
                csv.writer(f).writerow(
                    [now, site, name, previous_price, price, round(change_pct, 2) if change_pct is not None else "", url]
                )
            spider.logger.warning(
                f"PRICE CHANGE: [{site}] {name}: {previous_price} -> {price}"
            )

        self.conn.commit()
        return item
