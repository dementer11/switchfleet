from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from app.core.logging import configure_logging
from app.services.excel_lab_web_service import EXCEL_LAB_WEB_COMMANDS, ExcelLabWebError, ExcelLabWebService


WEB_ROOT = Path(__file__).resolve().parent / "web"
STATIC_ROOT = WEB_ROOT / "static"


class ExcelLabWebRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    inventory_path: str
    state_dir: str = ".switchfleet_lab"
    debug: bool = False


def create_local_web_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="SwitchFleet Local Web",
        version="0.3.0",
        description="DB-independent Excel-first local web UI for controlled lab switch administration.",
    )
    service = ExcelLabWebService()

    @app.get("/api/local/health", tags=["local-web"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "excel-first-local-web",
            "database_required": False,
            "production_apply_enabled": False,
            "commands": sorted(EXCEL_LAB_WEB_COMMANDS),
        }

    @app.post("/api/local/{command}", tags=["local-web"])
    def run_excel_lab_command(command: str, payload: ExcelLabWebRequest) -> dict[str, Any]:
        try:
            return service.run(command, payload.model_dump())
        except ExcelLabWebError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    if STATIC_ROOT.exists():
        app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
    return app


app = create_local_web_app()
