import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import config


class TestConfigDatabaseMode(unittest.TestCase):
    def tearDown(self):
        config.get_settings.cache_clear()

    def test_default_mode_falls_back_to_local_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with patch.dict(os.environ, {"DATA_DIR": str(data_dir)}, clear=True):
                config.get_settings.cache_clear()
                settings = config.get_settings()

            self.assertEqual(settings.database_mode, "sqlite")
            self.assertEqual(settings.database_url, f"sqlite:///{(data_dir / 'app.db').resolve().as_posix()}")

    def test_explicit_sqlite_mode_uses_local_default_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "sqlite-data"
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": str(data_dir),
                    "DATABASE_MODE": "sqlite",
                },
                clear=True,
            ):
                config.get_settings.cache_clear()
                settings = config.get_settings()

            self.assertEqual(settings.database_mode, "sqlite")
            self.assertEqual(settings.database_url, f"sqlite:///{(data_dir / 'app.db').resolve().as_posix()}")

    def test_sqlite_mode_supports_optional_sqlite_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            sqlite_path = Path(temp_dir) / "custom" / "pageindex-local.db"
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": str(data_dir),
                    "DATABASE_MODE": "sqlite",
                    "SQLITE_PATH": str(sqlite_path),
                },
                clear=True,
            ):
                config.get_settings.cache_clear()
                settings = config.get_settings()

            self.assertEqual(settings.database_mode, "sqlite")
            self.assertEqual(settings.database_url, f"sqlite:///{sqlite_path.resolve().as_posix()}")

    def test_mysql_mode_builds_database_url_from_mysql_parts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": str(Path(temp_dir) / "data"),
                    "DATABASE_MODE": "mysql",
                    "MYSQL_HOST": "db.example.internal",
                    "MYSQL_PORT": "3307",
                    "MYSQL_DATABASE": "pageindex",
                    "MYSQL_USER": "pageindex_user",
                    "MYSQL_PASSWORD": "s3cr3t",
                },
                clear=True,
            ):
                config.get_settings.cache_clear()
                settings = config.get_settings()

            self.assertEqual(settings.database_mode, "mysql")
            self.assertEqual(
                settings.database_url,
                "mysql+pymysql://pageindex_user:s3cr3t@db.example.internal:3307/pageindex",
            )

    def test_database_url_explicit_override_wins_over_database_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            override_url = "mysql+pymysql://legacy_user:legacy_pass@legacy-host:3306/legacy_db"
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": str(Path(temp_dir) / "data"),
                    "DATABASE_MODE": "sqlite",
                    "DATABASE_URL": override_url,
                    "MYSQL_HOST": "ignored-host",
                    "MYSQL_PORT": "3307",
                    "MYSQL_DATABASE": "ignored_db",
                    "MYSQL_USER": "ignored_user",
                    "MYSQL_PASSWORD": "ignored_password",
                },
                clear=True,
            ):
                config.get_settings.cache_clear()
                settings = config.get_settings()

            self.assertEqual(settings.database_mode, "mysql")
            self.assertEqual(settings.database_url, override_url)

    def test_routing_route_docs_mode_uses_canonical_env_before_legacy_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": str(Path(temp_dir) / "data"),
                    "ROUTING_ROUTE_DOCS_BUILD_MODE": "dry_run",
                    "ROUTING_ROUTE_DOC_BUILD_MODE": "persist",
                },
                clear=True,
            ):
                config.get_settings.cache_clear()
                settings = config.get_settings()

            self.assertEqual(settings.routing_route_docs_build_mode, "dry_run")

    def test_routing_route_docs_mode_supports_legacy_singular_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": str(Path(temp_dir) / "data"),
                    "ROUTING_ROUTE_DOC_BUILD_MODE": "persist",
                },
                clear=True,
            ):
                config.get_settings.cache_clear()
                settings = config.get_settings()

            self.assertEqual(settings.routing_route_docs_build_mode, "persist")


if __name__ == "__main__":
    unittest.main()
