import unittest

import requests

from ogna_test_auth import GATEWAY_URL, ZitadelTestUser


class TestApiHealth(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.user = ZitadelTestUser()

    @classmethod
    def tearDownClass(cls):
        cls.user.delete()

    def setUp(self):
        self.health = f"{GATEWAY_URL}/api/v1/health/"
        self.session = requests.session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.user.access_token()}",
            "Content-Type": "application/json",
        })

    def test_succesful_auth_call(self):
        result = self.session.get(url=self.health)
        self.assertEqual(result.status_code, 200)

    def test_no_login_call(self):
        result = requests.get(url=self.health)
        self.assertEqual(result.status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
