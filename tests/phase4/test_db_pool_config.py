import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from app.core import config


class TestDbPoolConfig(unittest.TestCase):
    def tearDown(self):
        config.get_settings.cache_clear()
        sys.modules.pop("app.core.db", None)

    def _import_db_with_env(self, env: dict[str, str]):
        config.get_settings.cache_clear()
        sys.modules.pop("app.core.db", None)
        with patch.dict(os.environ, env, clear=True):
            with patch("sqlalchemy.create_engine") as mock_create_engine:
                mock_create_engine.return_value = MagicMock(name="engine")
                module = importlib.import_module("app.core.db")
                return module, mock_create_engine

    def test_mysql_engine_receives_pool_parameters(self):
        _, mock_create_engine = self._import_db_with_env(
            {
                "DATABASE_URL": "mysql+pymysql://user:pass@db.example.test:3306/pageindex",
                "DB_POOL_PRE_PING": "true",
                "DB_POOL_RECYCLE_SECONDS": "1800",
                "DB_POOL_TIMEOUT_SECONDS": "5",
                "DB_POOL_SIZE": "3",
                "DB_MAX_OVERFLOW": "2",
            }
        )

        _, kwargs = mock_create_engine.call_args
        self.assertTrue(kwargs["future"])
        self.assertEqual(kwargs["connect_args"], {})
        self.assertTrue(kwargs["pool_pre_ping"])
        self.assertEqual(kwargs["pool_recycle"], 1800)
        self.assertEqual(kwargs["pool_timeout"], 5)
        self.assertEqual(kwargs["pool_size"], 3)
        self.assertEqual(kwargs["max_overflow"], 2)

    def test_sqlite_engine_does_not_receive_queuepool_parameters(self):
        _, mock_create_engine = self._import_db_with_env(
            {
                "DATABASE_URL": "sqlite:///:memory:",
            }
        )

        _, kwargs = mock_create_engine.call_args
        self.assertTrue(kwargs["future"])
        self.assertEqual(kwargs["connect_args"], {"check_same_thread": False})
        self.assertNotIn("pool_pre_ping", kwargs)
        self.assertNotIn("pool_recycle", kwargs)
        self.assertNotIn("pool_timeout", kwargs)
        self.assertNotIn("pool_size", kwargs)
        self.assertNotIn("max_overflow", kwargs)

    def test_pool_defaults_are_conservative_and_budgetable(self):
        with patch.dict(os.environ, {"DATABASE_URL": "mysql+pymysql://u:p@h:3306/db"}, clear=True):
            config.get_settings.cache_clear()
            settings = config.get_settings()

        self.assertTrue(settings.db_pool_pre_ping)
        self.assertEqual(settings.db_pool_recycle_seconds, 1800)
        self.assertEqual(settings.db_pool_timeout_seconds, 5)
        self.assertEqual(settings.db_pool_size, 3)
        self.assertEqual(settings.db_max_overflow, 2)
        self.assertTrue(settings.run_migrations_on_startup)


if __name__ == "__main__":
    unittest.main()
