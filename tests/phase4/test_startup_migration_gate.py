import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine

from app.core import bootstrap
from app.core.db import Base


class TestStartupMigrationGate(unittest.TestCase):
    def _settings(self, database_url: str, data_dir: Path):
        return SimpleNamespace(
            admin_username="admin",
            admin_password="changeme",
            llm_base_url="",
            llm_api_key="",
            secret_key="test-secret",
            database_url=database_url,
            data_dir=data_dir,
            run_migrations_on_startup=False,
        )

    def test_init_db_skips_migrations_when_disabled_but_still_seeds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "startup-gate.db"
            database_url = f"sqlite:///{db_path}"
            engine = create_engine(database_url, future=True, connect_args={"check_same_thread": False})
            self.addCleanup(engine.dispose)
            Base.metadata.create_all(bind=engine)

            with (
                patch.object(bootstrap, "engine", engine),
                patch.object(bootstrap, "get_settings", return_value=self._settings(database_url, Path(temp_dir))),
                patch.object(bootstrap, "_run_migrations") as mock_run_migrations,
            ):
                bootstrap.init_db()

            mock_run_migrations.assert_not_called()

    def test_migration_file_lock_context_is_usable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = SimpleNamespace(data_dir=Path(temp_dir))
            with patch.object(bootstrap, "get_settings", return_value=settings):
                with bootstrap._migration_file_lock():
                    self.assertTrue((Path(temp_dir) / "migration.lock").exists())


if __name__ == "__main__":
    unittest.main()
