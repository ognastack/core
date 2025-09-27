import unittest
import requests
import json
import uuid

class TestSignupAPI(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method"""
        self.base_url = "http://localhost:8000"
        self.signup_url = f"{self.base_url}/auth/signup"
        self.headers = {
            "Content-Type": "application/json"
        }

    def test_successful_signup(self):
        """Test successful user signup"""
        email = f"{str(uuid.uuid4())}@example.com"
        payload = {
            "email": email,
            "password": "strongpassword"
        }

        response = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(payload)
        )

        # Assert successful response
        self.assertEqual(response.status_code, 200)  # Or 200 depending on your API

        # Check response content (adjust based on your API response)
        response_data = response.json()

        self.assertIn("user", response_data)
        response_use = response_data['user']
        self.assertIn("email", response_use)
        self.assertEqual(response_use["email"], email)

    def test_signup_with_invalid_email(self):
        """Test signup with invalid email format"""
        payload = {
            "email": "invalid-email",
            "password": "strongpassword"
        }

        response = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(payload)
        )

        # Assert error response
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertIn("error_code", response_data)

    def test_signup_with_weak_password(self):
        """Test signup with weak password"""
        payload = {
            "email": "user@example.com",
            "password": "123"
        }

        response = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(payload)
        )

        # Assert error response
        self.assertEqual(response.status_code, 422)
        response_data = response.json()
        self.assertIn("error_code", response_data)

    def test_signup_missing_email(self):
        """Test signup with missing email field"""
        payload = {
            "password": "strongpassword"
        }

        response = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(payload)
        )

        # Assert error response
        self.assertEqual(response.status_code, 422)

    def test_signup_missing_password(self):
        """Test signup with missing password field"""
        payload = {
            "email": f"{str(uuid.uuid4())}@example.com"
        }

        response = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(payload)
        )

        # Assert error response
        self.assertEqual(response.status_code, 400)

    def test_signup_empty_payload(self):
        """Test signup with empty payload"""
        payload = {}

        response = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(payload)
        )

        # Assert error response
        self.assertEqual(response.status_code, 422)

    def test_duplicate_email_signup(self):
        """Test signup with already registered email"""
        payload = {
            "email": "existing@example.com",
            "password": "strongpassword"
        }

        # First signup (should succeed)
        response1 = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(payload)
        )

        # Second signup with same email (should fail)
        response2 = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(payload)
        )

        # Assert second request fails
        self.assertEqual(response2.status_code, 422)  # Conflict
        response_data = response2.json()
        self.assertIn("error_code", response_data)

    def test_server_connection(self):
        """Test if server is running and reachable"""
        try:
            response = requests.get(self.base_url, timeout=5)
            self.assertIsNotNone(response)
        except requests.exceptions.ConnectionError:
            self.fail("Cannot connect to server at http://localhost:8000")

    def tearDown(self):
        """Clean up after each test"""
        # Add any cleanup code here if needed
        # For example, delete test users from database
        pass


if __name__ == '__main__':
    # Run with more verbose output
    unittest.main(verbosity=2)

    # Alternative: Run specific test
    # unittest.main(defaultTest='TestSignupAPI.test_successful_signup')