"""
Spider for atida.com — search-driven, via its Algolia search API.

New model: Airflow hands this spider a `products` JSON (from Zoho CRM). For each
product we query atida's Algolia index by the product's brand+name and return
the best-matching hit's price, tagged with the product's EAN. No browser (atida
is behind a captcha/WAF); the JSON search endpoint the frontend uses answers
plain HTTP requests.

Public search-only credentials extracted from the site shell (2026-07). If this
starts returning 0 hits / 4xx, re-extract from the search page HTML (grep
"applicationId" / "apiKey" / index "atida_es_es_products").

Args (see _search.parse_products_arg):
    scrapy crawl competitor_atida -a products='[{"ean":"...","name":"...","brand":"..."}]'
    scrapy crawl competitor_atida -a query="avene solar spray" -a ean="8470..."
"""
import json
from urllib.parse import urlencode

import scrapy

from price_monitor.items import ProductItem
from price_monitor.spiders._search import parse_products_arg, search_term, match_score

ALGOLIA_HOST = "atida-spain-prod.topsort.workers.dev"
ALGOLIA_APP_ID = "M8GRS7KXGP"
ALGOLIA_API_KEY = (
    "N2RjMmUwMDZjY2Y5NjJmODI4ZmY5MDIzMmM0OGQ1Y2JhZWMwMGQzNzgwYjI5"
    "MWY3OWRiOTI3MTljMGRjOGM5MnRhZ0ZpbHRlcnM9"
)
INDEX = "atida_es_es_products"
HITS_PER_PAGE = 5  # we only need the top match per product


class AtidaSpider(scrapy.Spider):
    name = "competitor_atida"
    allowed_domains = ["topsort.workers.dev", "atida.com"]

    def __init__(self, products=None, query=None, ean=None, name=None, brand=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.products = parse_products_arg(products, query, ean, name, brand)

    async def start(self):
        if not self.products:
            self.logger.warning("No products provided (pass -a products='[...]'); nothing to search.")
            return
        for product in self.products:
            yield self._search_request(product)

    def _search_request(self, product):
        term = search_term(product)
        params = urlencode({"query": term, "hitsPerPage": HITS_PER_PAGE, "page": 0})
        body = json.dumps({"requests": [{"indexName": INDEX, "params": params}]})
        return scrapy.Request(
            f"https://{ALGOLIA_HOST}/1/indexes/*/queries",
            method="POST",
            headers={
                "x-algolia-application-id": ALGOLIA_APP_ID,
                "x-algolia-api-key": ALGOLIA_API_KEY,
                "Content-Type": "application/json",
                "Origin": "https://www.atida.com",
                "Referer": "https://www.atida.com/",
            },
            body=body,
            callback=self.parse,
            cb_kwargs={"product": product, "term": term},
            dont_filter=True,
        )

    def parse(self, response, product, term):
        data = json.loads(response.text)
        hits = (data.get("results") or [{}])[0].get("hits", [])
        yield self._item(product, term, hits[0] if hits else None)

    def _item(self, product, term, hit):
        item = ProductItem()
        item["site"] = "atida"
        item["input_ean"] = product.get("ean")
        item["query"] = term
        item["currency"] = "EUR"
        if not hit:
            item["matched"] = False
            item["match_score"] = 0.0
            return item
        item["matched"] = True
        item["name"] = hit.get("name")
        item["url"] = hit.get("url")
        item["sku"] = hit.get("sku")
        item["price"] = self._current_price(hit)
        item["in_stock"] = bool(hit.get("in_stock"))
        item["match_score"] = match_score(product.get("name"), hit.get("name"))
        return item

    @staticmethod
    def _current_price(hit):
        try:
            return float(hit["price"]["EUR"]["default"])
        except (KeyError, TypeError, ValueError):
            return None
