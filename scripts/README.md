# SwitchFleet Scripts

## Primary Lab Prototype

Use `excel_lab.py` for the operator-facing lab prototype.

```powershell
python scripts/excel_lab.py inventory.xlsx doctor
python scripts/excel_lab.py inventory.xlsx list
python scripts/excel_lab.py inventory.xlsx check-runtime --device 10.13.4.67
```

This path reads the Excel inventory directly, stores local JSON/JSONL state under `.switchfleet_lab/`, and does not require PostgreSQL, Alembic, FastAPI startup, or SQLAlchemy setup.

## Optional Enterprise Prototype

Use `lab_prototype.py` only when you intentionally want the DB-backed enterprise prototype path.

```powershell
python scripts/lab_prototype.py --help
```

That script uses SQLAlchemy-backed enterprise services and is secondary to the Excel-first lab workflow.
