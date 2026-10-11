def test_health_says_ok(client):
    answer = client.get("/health")
    assert answer.status_code == 200
    assert answer.json() == {"status": "ok"}
