import tempfile
import unittest
from pathlib import Path

from ogna_cli.cli import _compose_base_cmd, main


class TestOgnaCLI(unittest.TestCase):
    def test_init_scaffolds_clean_project_with_swappable_api_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "my-app"
            rc = main(["init", str(project_dir), "--api-image", "my-org/go-api:v1"])
            self.assertEqual(rc, 0)

            self.assertTrue((project_dir / ".env").exists())
            self.assertIn('API_IMAGE="my-org/go-api:v1"', (project_dir / ".env").read_text(encoding="utf-8"))
            self.assertFalse((project_dir / "api").exists())
            self.assertIn("image: ${API_IMAGE:-ogna-py-appi:prod}", (project_dir / "docker-compose.yaml").read_text(encoding="utf-8"))
            self.assertTrue((project_dir / "migrations" / "20260101000000_init.sql").exists())
            self.assertTrue((project_dir / ".ogna" / "docker-compose.core.yaml").exists())
            self.assertTrue((project_dir / ".ogna" / "docker-compose.storage.yaml").exists())

    def test_set_api_swaps_image_in_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "my-app"
            main(["init", str(project_dir)])

            rc = main(["set-api", "my-org/rust-api:v2", "-C", str(project_dir)])
            self.assertEqual(rc, 0)
            self.assertIn('API_IMAGE="my-org/rust-api:v2"', (project_dir / ".env").read_text(encoding="utf-8"))

    def test_add_service_updates_compose_and_extra_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "my-app"
            main(["init", str(project_dir)])

            rc = main([
                "add-service",
                "payments",
                "--image",
                "my-org/payments:v1",
                "--port",
                "8080",
                "--route",
                "/payments",
                "-C",
                str(project_dir),
            ])
            self.assertEqual(rc, 0)

            compose_text = (project_dir / "docker-compose.yaml").read_text(encoding="utf-8")
            self.assertIn("payments:", compose_text)
            self.assertIn("image: my-org/payments:v1", compose_text)

            env_text = (project_dir / ".env").read_text(encoding="utf-8")
            self.assertIn('OGNA_EXTRA_ROUTES="payments=http://payments:8080:/payments:jwt"', env_text)

    def test_init_with_scaffold_api_creates_local_api_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "my-app"
            rc = main(["init", str(project_dir), "--scaffold-api"])
            self.assertEqual(rc, 0)
            self.assertTrue((project_dir / "api" / "Dockerfile").exists())
            self.assertTrue((project_dir / "api" / "main.py").exists())

    def test_migration_new_creates_timestamped_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "my-app"
            main(["init", str(project_dir)])

            rc = main(["migration", "new", "add user profiles", "-C", str(project_dir)])
            self.assertEqual(rc, 0)

            migrations = list((project_dir / "migrations").glob("*_add_user_profiles.sql"))
            self.assertEqual(len(migrations), 1)
            content = migrations[0].read_text(encoding="utf-8")
            self.assertIn("-- migrate:up", content)
            self.assertIn("-- migrate:down", content)

    def test_track_table_and_console_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "my-app"
            main(["init", str(project_dir)])

            rc = main([
                "track-table",
                "public.profiles",
                "--owner-column",
                "user_id",
                "--columns",
                "id,user_id,username",
                "-C",
                str(project_dir),
            ])
            self.assertEqual(rc, 0)

            table_file = project_dir / "hasura" / "tables" / "public_profiles.yaml"
            self.assertTrue(table_file.exists())
            yaml_text = table_file.read_text(encoding="utf-8")
            self.assertIn("name: profiles", yaml_text)
            self.assertIn("_eq: X-Hasura-User-Id", yaml_text)
            self.assertIn("- username", yaml_text)

            rc_console = main(["console", "-C", str(project_dir)])
            self.assertEqual(rc_console, 0)
            env_text = (project_dir / ".env").read_text(encoding="utf-8")
            self.assertIn('HASURA_GRAPHQL_ENABLE_CONSOLE="true"', env_text)

            rc_disable = main(["console", "--disable", "-C", str(project_dir)])
            self.assertEqual(rc_disable, 0)
            env_text = (project_dir / ".env").read_text(encoding="utf-8")
            self.assertIn('HASURA_GRAPHQL_ENABLE_CONSOLE="false"', env_text)

    def test_compose_base_cmd_regenerates_missing_ogna_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "my-app"
            main(["init", str(project_dir)])

            # Simulate fresh git clone where .ogna/ was ignored
            for f in (project_dir / ".ogna").glob("*"):
                f.unlink()
            (project_dir / ".ogna").rmdir()

            cmd = _compose_base_cmd(project_dir)
            self.assertIn("--project-directory", cmd)
            self.assertTrue((project_dir / ".ogna" / "docker-compose.core.yaml").exists())
            self.assertTrue((project_dir / ".ogna" / "docker-compose.storage.yaml").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
