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
    assert "<loc>https://enoughy.com/cs</loc>" in answer.text
    assert "/intro" not in answer.text


HREFLANGS = [
    '<link rel="alternate" hreflang="en" href="https://enoughy.com/">',
    '<link rel="alternate" hreflang="cs" href="https://enoughy.com/cs">',
    '<link rel="alternate" hreflang="x-default" href="https://enoughy.com/">',
]


def test_the_czech_front_page_is_czech_and_its_own_address(client):
    answer = client.get("/cs")
    assert answer.status_code == 200
    assert '<html lang="cs">' in answer.text
    assert "Časový limit na PC vašeho dítěte." in answer.text
    assert 'href="https://testserver/install">enoughy.com/install' in answer.text  # the setup steps
    assert 'href="https://testserver/register">Registrovat' in answer.text
    assert '<link rel="canonical" href="https://enoughy.com/cs">' in answer.text
    for link in HREFLANGS:
        assert link in answer.text


def test_the_english_front_page_names_its_czech_twin(client):
    answer = client.get("/")
    assert '<html lang="en">' in answer.text
    assert '<link rel="canonical" href="https://enoughy.com/">' in answer.text
    for link in HREFLANGS:
        assert link in answer.text
