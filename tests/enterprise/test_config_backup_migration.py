from __future__ import annotations

import os
import subprocess
import sys


def test_config_backup_migration_upgrade_downgrade_upgrade(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "config-backup.sqlite"
    env = os.environ.copy()
    env["NCP_DATABASE_URL"] = f"sqlite+pysqlite:///{db_path.as_posix()}"
    upgrade = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, capture_output=True, text=True)
    downgrade = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "-1"], env=env, capture_output=True, text=True)
    upgrade_again = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, capture_output=True, text=True)

    assert upgrade.returncode == 0, upgrade.stderr
    assert downgrade.returncode == 0, downgrade.stderr
    assert upgrade_again.returncode == 0, upgrade_again.stderr
