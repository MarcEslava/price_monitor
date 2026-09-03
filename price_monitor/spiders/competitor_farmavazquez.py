"""
Spider for farmavazquez.com (PrestaShop 1.6) — search-driven.

New model: Airflow hands this spider a `products` JSON (from Zoho CRM). For each
product we hit PrestaShop's search (`/buscar?search_query=`) with the brand+name
and take the first result card as the best match, tagged with the product's EAN.

Confirmed selectors (server-rendered):
  - Product card: li.ajax_block_product
  - Name/URL:     a.product_img_link (title attr = full name)
  - Current price: span.product-price (excluding .old-price)
  - Stock:        .available-now present == in stock

Args (see _search.parse_products_arg):
    scrapy crawl competitor_farmavazquez -a products='[{"ean":"...","name":"...","brand":"..."}]'
"""
from urllib.parse import urlencode

import scrapy

from price_monitor.items import ProductItem
from price_monitor.spiders._search import parse_products_arg, search_term, match_score

SEARCH_URL = "https://www.farmavazquez.com/buscar?{}"


class FarmavazquezSpider(scrapy.Spider):
    name = "competitor_farmavazquez"
    allowed_domains = ["farmavazquez.com"]

    def __init__(self, products=None, query=None, ean=None, name=None, brand=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.products = parse_products_arg(products, query, ean, name, brand)

    async def start(self):
        if not self.products:
            self.logger.warning("No products provided (pass -a products='[...]'); nothing to search.")
            return
        for product in self.products:
            term = search_term(product)
            yield scrapy.Request(
                SEARCH_URL.format(urlencode({"search_query": term})),
                callback=self.parse,
                cb_kwargs={"product": product, "term": term},
                dont_filter=True,
            )

    def parse(self, response, product, term):
        card = response.css("li.ajax_block_product")
        if not card:
            yield self._miss(product, term)
            return
        card = card[0]

        img_link = card.css("a.product_img_link")
        url = img_link.attrib.get("href")
        name = img_link.attrib.get("title")
        price_text = card.css("span.product-price:not(.old-price)::text").get()

        item = ProductItem()
        item["site"] = "farmavazquez"
        item["input_ean"] = product.get("ean")
        item["query"] = term
        item["currency"] = "EUR"
        item["matched"] = bool(url)
        item["name"] = name.strip() if name else None
        item["url"] = response.urljoin(url) if url else None
        item["price"] = self._parse_price(price_text)
        item["in_stock"] = bool(card.css(".available-now"))
        item["match_score"] = match_score(product.get("name"), name)
        yield item

    def _miss(self, product, term):
        item = ProductItem()
        item["site"] = "farmavazquez"
        item["input_ean"] = product.get("ean")
        item["query"] = term
        item["currency"] = "EUR"
        item["matched"] = False
        item["match_score"] = 0.0
        return item

    @staticmethod
    def _parse_price(text):
        if not text:
            return None
        cleaned = text.strip().replace("\xa0", " ")
        cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch in ",.")
        cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
