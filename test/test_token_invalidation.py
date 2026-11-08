import base64
import json
import os
import unittest
import uuid

import requests


def _jwt_claims(token):
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


class TestLogoutTokenInvalidation(unittest.TestCase):
    """Logout revokes refresh tokens; access tokens are short-lived (GOTRUE_JWT_EXP)."""

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
        self.assertIn("access_token", body)
        self.assertIn("refresh_token", body)
        return body["access_token"], body["refresh_token"]

    def _authed(self, access_token):
        session = requests.session()
        session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })
        return session

    def test_access_token_is_short_lived(self):
        access_token, _ = self._sign_in()
        claims = _jwt_claims(access_token)
        max_exp = int(os.environ.get("GOTRUE_JWT_EXP", "600"))
        self.assertLessEqual(claims["exp"] - claims["iat"], max_exp)

    def test_logout_revokes_refresh_token(self):
        access_token, refresh_token = self._sign_in()
        session = self._authed(access_token)

        self.assertEqual(session.get(self.health).status_code, 200)

        # Refresh works while logged in (and rotates the refresh token)
        refreshed = requests.post(self.refresh_url, headers=self.headers,
                                  json={"refresh_token": refresh_token})
        self.assertEqual(refreshed.status_code, 200)
        access_token = refreshed.json()["access_token"]
        refresh_token = refreshed.json()["refresh_token"]
        session = self._authed(access_token)

        logout = session.post(self.logout_url)
        self.assertEqual(logout.status_code, 204)

        # After logout the refresh token can no longer mint new access tokens
        after = requests.post(self.refresh_url, headers=self.headers,
                              json={"refresh_token": refresh_token})
        self.assertIn(after.status_code, (400, 401))
        self.assertNotIn("access_token", after.json())

        # Signing in again starts a fresh, working session
        new_access, _ = self._sign_in()
        self.assertEqual(self._authed(new_access).get(self.health).status_code, 200)

    def test_no_login_call(self):
        self.assertEqual(requests.get(self.health).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
