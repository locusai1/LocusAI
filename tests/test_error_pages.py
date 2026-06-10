# tests/test_error_pages.py — error pages must render for logged-out users
# (they extend the standalone public_base.html, not the auth dashboard layout).


class TestErrorPages:
    def test_404_renders_for_anonymous(self, client):
        resp = client.get("/this-route-does-not-exist-xyz")
        assert resp.status_code == 404
        body = resp.get_data(as_text=True)
        assert "Page not found" in body
        # public chrome present (not the auth dashboard sidebar)
        assert "Sign in" in body

    def test_403_renders_for_anonymous(self, client):
        # POST to a non-exempt path with no CSRF token -> custom CSRF aborts 403,
        # before any login check. The 403 page must render cleanly for anon users.
        resp = client.post("/billing/checkout/starter")
        assert resp.status_code == 403
        body = resp.get_data(as_text=True)
        assert "Sign in" in body  # rendered via public_base, no traceback

    def test_404_for_logged_in_user_shows_dashboard_link(self, authenticated_client):
        resp = authenticated_client.get("/nope-not-here-123")
        assert resp.status_code == 404
        body = resp.get_data(as_text=True)
        assert "Dashboard" in body
