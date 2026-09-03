"""
Working example spider against https://books.toscrape.com/ — a public
sandbox site built for scraping practice (fake bookstore with prices).

Run it with:
    scrapy crawl books_example

Use this as a reference for the shape of a real spider: pagination,
price parsing, and yielding a ProductItem for the pipeline to store.
"""
import scrapy

from price_monitor.items import ProductItem


class BooksExampleSpider(scrapy.Spider):
    name = "books_example"
    allowed_domains = ["books.toscrape.com"]
    start_urls = ["https://books.toscrape.com/catalogue/category/books_1/index.html"]

    def parse(self, response):
        for book in response.css("article.product_pod"):
            price_text = book.css("p.price_color::text").get(default="")
            price = self._parse_price(price_text)

            item = ProductItem()
            item["site"] = "books_toscrape"
            item["name"] = book.css("h3 a::attr(title)").get()
            item["url"] = response.urljoin(book.css("h3 a::attr(href)").get())
            item["price"] = price
            item["currency"] = "GBP"
            item["in_stock"] = "In stock" in book.css("p.instock.availability::text").getall()[-1] \
                if book.css("p.instock.availability::text").getall() else None
            yield item

        next_page = response.css("li.next a::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    @staticmethod
    def _parse_price(text):
        # e.g. "£51.77" -> 51.77
        cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
