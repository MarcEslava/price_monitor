import scrapy


class ProductItem(scrapy.Item):
    # Which spider/competitor this came from, e.g. "Primor_store"
    site = scrapy.Field()

    # Product identity
    name = scrapy.Field()
    url = scrapy.Field()
    sku = scrapy.Field()          # optional, fill in if the site exposes one

    # Price (always store as a plain float, currency separate)
    price = scrapy.Field()
    currency = scrapy.Field()

    # Availability, useful context for alerts
    in_stock = scrapy.Field()

    # --- Search-driven matching (Airflow sends the product to look up) ---
    # The EAN we searched FOR (from Zoho). Because we drive the search from a
    # product whose EAN we already know, the competitor price comes back keyed
    # to your catalog even when the competitor never publishes an EAN.
    input_ean = scrapy.Field()
    query = scrapy.Field()          # the exact search term used
    match_score = scrapy.Field()    # 0..1 name-overlap confidence of the chosen hit
    matched = scrapy.Field()        # bool: did the search return any candidate