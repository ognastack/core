import time
import unittest

import requests

from ogna_test_auth import ACTIVE_CACHE_TTL, AUTH_HOST, GATEWAY_URL, ZitadelTestUser, auth_request

HEALTH = f"{GATEWAY_URL}/api/v1/health/"


class TestAuthGateway(unittest.TestCase):
    """The gateway accepts only active Zitadel tokens and honours revocation."""

    @classmethod
    def setUpClass(cls):
        cls.user = ZitadelTestUser()

    @classmethod
    def tearDownClass(cls):
        cls.user.delete()

    def _get(self, token=None, url=HEALTH, extra=None):
        headers = dict(extra or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return requests.get(url, headers=headers, timeout=15)

    def test_discovery_served_on_auth_domain(self):
        r = auth_request("GET", "/.well-known/openid-configuration")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["issuer"].rstrip("/"), f"http://{AUTH_HOST}")

    def test_no_token_rejected(self):
        self.assertEqual(self._get().status_code, 401)

    def test_garbage_token_rejected(self):
        self.assertEqual(self._get("not-a-real-token").status_code, 401)

    def test_spoofed_identity_headers_do_not_authenticate(self):
        r = self._get(extra={"X-Authenticated-User-Id": "someone", "X-Hasura-Admin-Secret": "guess"})
        self.assertEqual(r.status_code, 401)

    def test_valid_token_accepted(self):
        self.assertEqual(self._get(self.user.access_token()).status_code, 200)

    def test_revoked_token_rejected(self):
        token = self.user.access_token()
        self.assertEqual(self._get(token).status_code, 200)

        self.user.revoke(token)
        time.sleep(ACTIVE_CACHE_TTL + 1)

        self.assertEqual(self._get(token).status_code, 401)

    def test_new_token_after_revocation_works(self):
        old = self.user.access_token()
        self.user.revoke(old)
        self.assertEqual(self._get(self.user.access_token()).status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
