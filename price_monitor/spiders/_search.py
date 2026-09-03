"""
Shared helpers for search-driven spiders.

The new model: Airflow (Price Monitor ETL) pulls the product list from Zoho CRM
and hands each spider a `products` argument — a JSON list of the products to
look up. Each spider SEARCHES its competitor for each product and returns the
best-matching listing's price, tagged with the product's EAN. Because we drive
the search from a product whose EAN we already know, matching is solved even for
sites that never expose an EAN.

Spider args (passed by Scrapyd `schedule.json -d ...`):
    products = '[{"ean": "8470...", "name": "Avène Solar ...", "brand": "Avene"}, ...]'
  or a single product for ad-hoc testing:
    query = "avene solar spray", ean = "8470...", brand = "Avene"
"""
import json
import re


def parse_products_arg(products=None, query=None, ean=None, name=None, brand=None):
    """Normalise spider args into a list of {ean, name, brand} dicts."""
    if products:
        data = json.loads(products) if isinstance(products, str) else products
        return [_norm(p) for p in data if (p.get("name") or p.get("query"))]
    if query or name:
        return [_norm({"ean": ean, "name": name or query, "brand": brand})]
    return []


def _norm(p):
    return {
        "ean": str(p.get("ean") or "").strip(),
        "name": str(p.get("name") or p.get("query") or "").strip(),
        "brand": str(p.get("brand") or "").strip(),
    }


def search_term(product):
    """Build the search string: brand first (helps relevance), then name, deduped."""
    seen, out = set(), []
    for tok in f"{product.get('brand', '')} {product.get('name', '')}".split():
        low = tok.lower()
        if low not in seen:
            seen.add(low)
            out.append(tok)
    return " ".join(out).strip() or product.get("name", "")


def _tokens(s):
    return [t for t in re.sub(r"[^\w]+", " ", (s or "").lower()).split() if len(t) > 1]


def match_score(query_name, candidate_name):
    """Fraction of the product's tokens present in the candidate's name (0..1).

    A cheap confidence signal so the pricing side can trust / review a match;
    it is NOT the matching mechanism (the EAN is), just a quality flag.
    """
    a, b = set(_tokens(query_name)), set(_tokens(candidate_name))
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a), 3)
