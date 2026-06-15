# SwitchFleet Scripts

## Primary Lab Prototype

Use the installed `switchfleet` command for the operator-facing lab prototype.

```powershell
switchfleet inventory.xlsx doctor
switchfleet inventory.xlsx summary
switchfleet inventory.xlsx list
switchfleet inventory.xlsx check-runtime --device 192.0.2.67
```

This path reads the Excel inventory directly, stores local JSON/JSONL state under `.switchfleet_lab/`, and does not require PostgreSQL, Alembic, FastAPI startup, or SQLAlchemy setup.

The same `switchfleet` CLI is the supported local entrypoint on Windows, Linux, and macOS after `pip install -e .` or package installation.

The source-checkout compatibility form is still available as `python scripts/excel_lab.py`.

## Optional Enterprise Prototype

Use `lab_prototype.py` only when you intentionally want the DB-backed enterprise prototype path.

```powershell
python scripts/lab_prototype.py --help
```

That script uses SQLAlchemy-backed enterprise services and is secondary to the Excel-first lab workflow.
