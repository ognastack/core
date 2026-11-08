import base64
import json
import os
import time
import unittest
import uuid

import requests

# Max seconds an "active session" result is cached by the gateway (ogna-guard session_cache_ttl)
SESSION_CACHE_TTL = int(os.environ.get("OGNA_SESSION_CACHE_TTL", "5"))


def _jwt_claims(token):
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


class TestLogoutTokenInvalidation(unittest.TestCase):
    """Logout ends the GoTrue session; the gateway rejects every token from that session."""

    def setUp(self):
        self.base_url = "http://localhost:8000"
        self.signup_url = f"{self.base_url}/auth/signup"
        self.logout_url = f"{self.base_url}/auth/logout"
        self.sign_in_url = f"{self.base_url}/auth/token?grant_type=password"
        self.refresh_url = f"{self.base_url}/auth/token?grant_type=refresh_token"
        self.health = f"{self.base_url}/api/v1/health/"
        self.headers = {"Content-Type": "application/json"}

        email = f"{uuid.uuid4()}@example.com"
        self.payload = {"email": email, "password": "strongpassword"}

        response = requests.post(self.signup_url, headers=self.headers, json=self.payload)
        self.assertEqual(200, response.status_code)
        self.assertEqual(response.json()["user"]["email"], email)

    def _sign_in(self):
        response = requests.post(self.sign_in_url, headers=self.headers, json=self.payload)
        self.assertEqual(200, response.status_code)
        body = response.json()
        return body["access_token"], body["refresh_token"]

    def _authed(self, access_token):
        session = requests.session()
        session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })
        return session

    def _wait_for_cache(self):
        time.sleep(SESSION_CACHE_TTL + 1)

    def test_tokens_carry_session_id(self):
        access_token, _ = self._sign_in()
        self.assertIn("session_id", _jwt_claims(access_token))

    def test_logout_rejects_access_token(self):
        access_token, _ = self._sign_in()
        session = self._authed(access_token)
        self.assertEqual(session.get(self.health).status_code, 200)

        self.assertEqual(session.post(self.logout_url).status_code, 204)
        self._wait_for_cache()

        self.assertEqual(session.get(self.health).status_code, 401)

    def test_logout_rejects_every_token_of_the_session(self):
        """A token stolen before a refresh is also rejected once the session ends."""
        old_access, refresh_token = self._sign_in()

        refreshed = requests.post(self.refresh_url, headers=self.headers,
                                  json={"refresh_token": refresh_token})
        self.assertEqual(refreshed.status_code, 200)
        new_access = refreshed.json()["access_token"]
        new_refresh = refreshed.json()["refresh_token"]
        self.assertEqual(_jwt_claims(old_access)["session_id"], _jwt_claims(new_access)["session_id"])

        self.assertEqual(self._authed(old_access).get(self.health).status_code, 200)
        self.assertEqual(self._authed(new_access).post(self.logout_url).status_code, 204)
        self._wait_for_cache()

        self.assertEqual(self._authed(old_access).get(self.health).status_code, 401)
        self.assertEqual(self._authed(new_access).get(self.health).status_code, 401)

        after = requests.post(self.refresh_url, headers=self.headers,
                              json={"refresh_token": new_refresh})
        self.assertIn(after.status_code, (400, 401))

    def test_new_sign_in_after_logout_works(self):
        access_token, _ = self._sign_in()
        self.assertEqual(self._authed(access_token).post(self.logout_url).status_code, 204)

        new_access, _ = self._sign_in()
        self.assertEqual(self._authed(new_access).get(self.health).status_code, 200)

    def test_no_login_call(self):
        self.assertEqual(requests.get(self.health).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
