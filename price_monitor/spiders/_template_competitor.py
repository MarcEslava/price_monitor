"""
TEMPLATE — copy per competitor. Two modes; pick the one the site allows.

The pricing pipeline is search-driven: Airflow (Price Monitor ETL) pulls the
product list from Zoho CRM and hands each spider a `products` JSON. How a spider
uses it depends on what the competitor permits:

  MODE A — search-driven (preferred; see competitor_atida / competitor_farmavazquez)
    For each product, SEARCH the site for it and return the best match, tagged
    with the product's EAN. Works when the site allows search (robots.txt) or
    exposes a search API. Matching is solved because we drive from a known EAN.

  MODE B — category-crawl + offline match (see competitor_primor)
    When search is disallowed by robots.txt, crawl the allowed category pages,
    emit RAW listings, and let the ETL match them to the catalog by name+brand
    (using price_monitor.spiders._search.match_score). Use a `categories` arg.

Before scraping: check robots.txt and Terms of Service. Keep ROBOTSTXT_OBEY on.

Steps:
  1. Rename the class and `name`.
  2. Set allowed_domains.
  3. Pick a mode and fill in the request + parsing (reuse the confirmed selectors
     pattern from the two real spiders).
  4. Emit ProductItem with input_ean/query/match_score for MODE A, or raw
     site/name/url/price for MODE B.
"""
import scrapy

from price_monitor.items import ProductItem
from price_monitor.spiders._search import parse_products_arg, search_term, match_score


class CompetitorTemplateSpider(scrapy.Spider):
    name = "competitor_template"  # TODO rename, e.g. "competitor_acme"
    allowed_domains = ["example.com"]  # TODO

    def __init__(self, products=None, query=None, ean=None, name=None, brand=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # MODE A: the list of products to look up (from Airflow/Zoho).
        self.products = parse_products_arg(products, query, ean, name, brand)

    async def start(self):
        if not self.products:
            self.logger.warning("No products provided; nothing to search.")
            return
        for product in self.products:
            term = search_term(product)
            yield scrapy.Request(
                f"https://example.com/search?q={term}",  # TODO real search URL
                callback=self.parse,
                cb_kwargs={"product": product, "term": term},
                dont_filter=True,
            )

    def parse(self, response, product, term):
        card = response.css("PRODUCT_CARD_SELECTOR")  # TODO
        item = ProductItem()
        item["site"] = "competitor_shortname"  # TODO
        item["input_ean"] = product.get("ean")
        item["query"] = term
        item["currency"] = "EUR"  # TODO
        if not card:
            item["matched"] = False
            item["match_score"] = 0.0
            yield item
            return
        card = card[0]
        name = card.css("NAME_SELECTOR::text").get()  # TODO
        url = card.css("LINK_SELECTOR::attr(href)").get()  # TODO
        item["matched"] = bool(url)
        item["name"] = name.strip() if name else None
        item["url"] = response.urljoin(url) if url else None
        item["price"] = self._parse_price(card.css("PRICE_SELECTOR::text").get())  # TODO
        item["in_stock"] = None  # TODO
        item["match_score"] = match_score(product.get("name"), name)
        yield item

    @staticmethod
    def _parse_price(text):
        if not text:
            return None
        import re
        m = re.search(r"[\d.,]+", text)
        if not m:
            return None
        cleaned = m.group(0).replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
