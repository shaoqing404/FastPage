import os
import unittest

class TestPhase4MigrationsSmoke(unittest.TestCase):
    def setUp(self):
        try:
            from alembic.config import Config
            self.Config = Config
            from alembic import command
            self.command = command
        except ImportError:
            self.skipTest("alembic is not installed. Skipping migration smoke test.")
            
        self.db_url = "sqlite:///:memory:"
        self.alembic_cfg = self.Config("alembic.ini")
        self.alembic_cfg.set_main_option("sqlalchemy.url", self.db_url)
        
    def test_local_phase4_upgrade_downgrade(self):
        # Alembic command should fail normally if there are real migration defects,
        # we do not catch and swallow exceptions here anymore.
        
        # Stamp to 0005 (before Phase 4)
        self.command.stamp(self.alembic_cfg, "20260407_0005_phase3_compliance_api")
        
        # Upgrade to Phase 4 schemas
        self.command.upgrade(self.alembic_cfg, "20260410_0007_phase4_backfill_membership_visibility")
        
        # Downgrade back to test downgrade paths
        self.command.downgrade(self.alembic_cfg, "20260407_0005_phase3_compliance_api")
        
        # Upgrade again to leave state correctly if needed
        self.command.upgrade(self.alembic_cfg, "20260410_0007_phase4_backfill_membership_visibility")
        
        self.assertTrue(True, "Migration smoke test completed successfully.")

if __name__ == "__main__":
    unittest.main()
