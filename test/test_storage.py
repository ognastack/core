import unittest
import requests
import json
import uuid
import io


class TestStorage(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method"""
        self.base_url = "http://localhost:8000"
        self.signup_url = f"{self.base_url}/auth/signup"
        self.logout_url = f"{self.base_url}/auth/logout"
        self.sign_in = f"{self.base_url}/auth/token?grant_type=password"

        self.storage_base = f"{self.base_url}/storage/v1"
        self.storage_buckets = f"{self.storage_base}/buckets/"
        self.storage_objs = f"{self.storage_base}/objects"

        self.health = f"{self.base_url}/api/v1/health/"

        self.check = f"{self.base_url}/api/v1/check/"
        self.headers = {
            "Content-Type": "application/json"
        }

        email = f"{str(uuid.uuid4())}@example.com"
        self.payload = {
            "email": email,
            "password": "strongpassword"
        }

        response = requests.post(
            self.signup_url,
            headers=self.headers,
            data=json.dumps(self.payload)
        )

        # Assert successful response
        self.assertEqual(200, response.status_code)  # Or 200 depending on your API

        # Check response content (adjust based on your API response)
        response_data = response.json()

        self.assertIn("user", response_data)
        response_use = response_data['user']
        self.assertIn("email", response_use)
        self.assertEqual(response_use["email"], email)

        response_sign_in = requests.post(self.sign_in, headers=self.headers, json=self.payload)

        self.assertIn("access_token", response_sign_in.json())

        self.access_token = response_sign_in.json()["access_token"]

        # Create session
        self.session = requests.session()

        # Set headers including authorization
        self.session.headers.update({
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        })

    def test_create_bucket(self):
        data = {
            "name": str(uuid.uuid4()),
            "public": False
        }
        print(self.storage_buckets)
        print(self.session.post(self.storage_buckets, json=data).json())

    def test_upload_file_to_bucket(self):
        bucket_name = f"test-bucket-{uuid.uuid4()}"
        bucket_data = {"name": bucket_name, "public": False}
        print(self.session.post(self.storage_buckets, json=bucket_data).json())

        # 2. Prepare the file
        file_content = b"Hello World, this is a test file."
        file_name = "test_document.txt"

        files = {
            'file': (file_name, io.BytesIO(file_content), 'text/plain')
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)
        self.assertEqual(response.status_code, 201, f"Upload failed: {response.text}")

        response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)
        self.assertEqual(response.status_code, 201, f"Upload failed: {response.text}")

        response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)
        self.assertEqual(response.status_code, 201, f"Upload failed: {response.text}")

        response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)
        self.assertEqual(response.status_code, 201, f"Upload failed: {response.text}")

    def test_upload_delete_file(self):
        bucket_name = f"test-bucket-{uuid.uuid4()}"
        bucket_data = {"name": bucket_name, "public": False}
        print(self.session.post(self.storage_buckets, json=bucket_data).json())

        # 2. Prepare the file
        file_content = b"Hello World, this is a test file."
        file_name = "deletion_document.txt"

        files = {
            'file': (file_name, io.BytesIO(file_content), 'text/plain')
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)
        self.assertEqual(response.status_code, 201, f"Upload failed: {response.text}")

        response = requests.delete(f"{self.storage_objs}/{bucket_name}/{file_name}", headers=headers)
        self.assertEqual(response.status_code, 201, f"Delete failed: {response.text}")

    def test_download_file(self):
        bucket_name = f"test-bucket-{uuid.uuid4()}"
        bucket_data = {"name": bucket_name, "public": False}
        print(self.session.post(self.storage_buckets, json=bucket_data).json())

        # 2. Prepare the file
        file_content = b"Hello World, this is a test file."
        file_name = "deletion_document.txt"

        files = {
            'file': (file_name, io.BytesIO(file_content), 'text/plain')
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)
        self.assertEqual(response.status_code, 201, f"Upload failed: {response.text}")

        # 3. Download the file
        response = requests.get(f"{self.storage_objs}/{bucket_name}/{file_name}", headers=headers)

        # Assertions
        self.assertEqual(response.status_code, 200, f"Download failed: {response.text}")

        # Validate the contents match exactly
        self.assertEqual(response.content, file_content, "Downloaded file content does not match original")

        # Optional: Validate headers sent by FileResponse
        self.assertIn(f'filename="{file_name}"', response.headers["content-disposition"])

    def test_download_existing_file_fron_non_existing_bucket(self):
        bucket_name = f"test-bucket-{uuid.uuid4()}"
        bucket_data = {"name": bucket_name, "public": False}
        print(self.session.post(self.storage_buckets, json=bucket_data).json())

        # 2. Prepare the file
        file_content = b"Hello World, this is a test file."
        file_name = "deletion_document.txt"

        files = {
            'file': (file_name, io.BytesIO(file_content), 'text/plain')
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)
        self.assertEqual(response.status_code, 201, f"Upload failed: {response.text}")

        # 3. Download the file
        response = requests.get(f"{self.storage_objs}/{str(uuid.uuid4())}/{file_name}", headers=headers)

        # Assertions
        self.assertEqual(response.status_code, 404, f"Download failed: {response.text}")


    def test_list_files(self):
        bucket_name = f"test-bucket-{uuid.uuid4()}"
        bucket_data = {"name": bucket_name, "public": False}
        print(self.session.post(self.storage_buckets, json=bucket_data).json())

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        file_names = [str(f"file_{a}_tes.json") for a in range(0, 4)]

        for file_name in file_names:
            # 2. Prepare the file
            file_content = b"Hello World, this is a test file."

            files = {
                'file': (file_name, io.BytesIO(file_content), 'text/plain')
            }
            response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)
            self.assertEqual(response.status_code, 201, f"Upload failed: {response.text}")

        response = requests.get(f"{self.storage_objs}/{bucket_name}", headers=headers)

        list_files = response.json()
        print(list_files)
        self.assertGreater(len(list_files), 0)
        self.assertEqual(len(list_files), len(file_names))

        for fil_e in list_files:
            print(f"checking {fil_e['name']}")
            self.assertIn(fil_e['name'], file_names)

    def test_download_non_existing_file(self):
        bucket_name = f"test-bucket-{uuid.uuid4()}"
        bucket_data = {"name": bucket_name, "public": False}
        print(self.session.post(self.storage_buckets, json=bucket_data).json())

        file_name = "deletion_document.txt"

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        # 3. Download the file
        response = requests.get(f"{self.storage_objs}/{bucket_name}/{file_name}", headers=headers)

        # Assertions
        self.assertEqual(response.status_code, 404, f"Download failed: {response.text}")

    def test_upload_delete_non_existing_file(self):
        bucket_name = f"test-bucket-{uuid.uuid4()}"
        bucket_data = {"name": bucket_name, "public": False}
        print(self.session.post(self.storage_buckets, json=bucket_data).json())

        file_name = "deletion_document.txt"

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        response = requests.delete(f"{self.storage_objs}/{bucket_name}/{file_name}", headers=headers)
        self.assertEqual(response.status_code, 404, f"Delete failed: {response.text}")

    def test_upload_non_existing_bucket(self):
        bucket_name = f"test-bucket-{uuid.uuid4()}"

        # 2. Prepare the file
        file_content = b"Hello World, this is a test file."
        file_name = "test_document.txt"

        files = {
            'file': (file_name, io.BytesIO(file_content), 'text/plain')
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        response = requests.post(f"{self.storage_objs}/{bucket_name}", files=files, headers=headers)

        # 4. Assertions
        self.assertEqual(response.status_code, 404, f"Upload failed: {response.text}")

    def tearDown(self):
        """Clean up after each test"""
        # Add any cleanup code here if needed
        # For example, delete test users from database
        pass


if __name__ == '__main__':
    # Run with more verbose output
    unittest.main(verbosity=2)
