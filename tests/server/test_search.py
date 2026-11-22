"""Search engines are told which pages to index and where to find them."""


def test_robots_points_to_the_sitemap_and_skips_the_api(client):
    answer = client.get("/robots.txt")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/plain")
    assert "Sitemap: https://enoughy.com/sitemap.xml" in answer.text
    assert "Disallow: /api/" in answer.text


def test_sitemap_lists_the_front_page_at_its_bare_address(client):
    answer = client.get("/sitemap.xml")
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/xml"
    assert "<loc>https://enoughy.com/</loc>" in answer.text
    assert "/intro" not in answer.text
