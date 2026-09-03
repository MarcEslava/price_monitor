"""
Spider for primor.eu (Magento 2) — category-crawl (NOT search-driven).

Why different from atida/farmavazquez: primor's robots.txt disallows search
(`/*?q=`, `/*?tag=`, `/*?orderby=` ...), so we cannot look products up one by
one politely. Browsing category pages IS allowed (pagination uses `?p=N`, which
robots permits), so this spider crawls the configured categories and emits every
listing as a RAW item (site/name/url/price). Matching those to your Zoho catalog
by name+brand (with the shared match_score gate) happens OFFLINE in the Price
Monitor ETL, where the catalog lives.

Confirmed selectors (server-rendered):
  - Product card: form.product-item
  - Name/URL:     a.product-item-link
  - Price:        .price-wrapper[data-price-type="finalPrice"] @data-price-amount

Args:
    categories = '["https://www.primor.eu/es_es/perfumes-de-mujer", ...]'
                 (JSON list or comma-separated). Airflow passes the categories
                 that cover the products you price. Falls back to a demo default.
"""
import json
import math
import re

import scrapy

from price_monitor.items import ProductItem

ITEMS_PER_PAGE_DEFAULT = 24
MAX_PAGES = 100  # safety cap per category so a mis-parsed count can't run away

DEFAULT_CATEGORIES = ["https://www.primor.eu/es_es/perfumes-de-mujer"]


class PrimorSpider(scrapy.Spider):
    name = "competitor_primor"
    allowed_domains = ["primor.eu", "www.primor.eu"]
    # Scrapy 2.13's downloader OffsiteMiddleware was filtering our own primor.eu
    # start requests; disable it for this deliberate first-party category crawl.
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "scrapy.downloadermiddlewares.offsite.OffsiteMiddleware": None,
        },
    }

    def __init__(self, categories=None, products=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.categories = self._parse_categories(categories) or DEFAULT_CATEGORIES

    @staticmethod
    def _parse_categories(categories):
        if not categories:
            return []
        try:
            data = json.loads(categories)
            if isinstance(data, list):
                return [str(u).strip() for u in data if str(u).strip()]
        except (ValueError, TypeError):
            pass
        return [u.strip() for u in str(categories).split(",") if u.strip()]

    async def start(self):
        for url in self.categories:
            # dont_filter so start() requests aren't dropped by the offsite
            # middleware (start_urls used to be auto-exempt; start() ones aren't).
            yield scrapy.Request(url, callback=self.parse, dont_filter=True)

    def parse(self, response):
        for card in response.css("form.product-item"):
            name_link = card.css("a.product-item-link")
            name = name_link.css("::text").get()
            url = name_link.attrib.get("href")
            if not url:
                continue
            final_price = card.css(
                '.price-wrapper[data-price-type="finalPrice"]::attr(data-price-amount)'
            ).get()

            item = ProductItem()
            item["site"] = "primor"
            item["name"] = name.strip() if name else None
            item["url"] = response.urljoin(url)
            item["price"] = float(final_price) if final_price else None
            item["currency"] = "EUR"
            item["in_stock"] = True  # this theme shows no OOS badge on listing cards
            yield item

        # Pagination via ?p=N (robots-allowed), computed once from the total count.
        if "p=" not in response.url:
            match = re.search(r"de\s+([\d.,]+)\s+productos", response.text, re.IGNORECASE)
            if match:
                total_products = int(re.sub(r"[.,]", "", match.group(1)))
                total_pages = min(math.ceil(total_products / ITEMS_PER_PAGE_DEFAULT), MAX_PAGES)
                sep = "&" if "?" in response.url else "?"
                for page_num in range(2, total_pages + 1):
                    yield response.follow(
                        f"{response.url}{sep}p={page_num}", callback=self.parse, dont_filter=True
                    )
            else:
                self.logger.warning(
                    "Product count not found on %s — only page 1 scraped.", response.url
                )
