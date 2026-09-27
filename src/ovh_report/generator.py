from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from importlib.resources import files
from pathlib import Path

from plotly.offline.offline import get_plotlyjs


ASSET_NAMES = ("index.html", "style.css", "app.js")


def write_output(report: dict, output_dir: Path, input_dir: Path) -> None:
    output_dir = output_dir.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        (temp_dir / "report.json").write_text(serialized + "\n", encoding="utf-8")
        compact = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
        (temp_dir / "data.js").write_text(f"window.OVH_REPORT={compact};\n", encoding="utf-8")
        (temp_dir / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
        pdf_dir = temp_dir / "pdfs"
        pdf_dir.mkdir()
        for invoice in report["invoices"]:
            filename = invoice["source_file"]
            relative_source = Path(filename)
            if relative_source.is_absolute() or ".." in relative_source.parts:
                raise ValueError(f"Virheellinen PDF-tiedostonimi: {filename}")
            source = input_dir / relative_source
            if not source.is_file():
                raise FileNotFoundError(f"Raportin lähde-PDF puuttuu: {source}")
            destination = temp_dir / invoice["pdf_path"]
            if destination.parent.parent != pdf_dir:
                raise ValueError(f"Virheellinen output-PDF-polku: {invoice['pdf_path']}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        assets = files("ovh_report.assets")
        for name in ASSET_NAMES:
            (temp_dir / name).write_text(assets.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
        backup_dir: Path | None = None
        if output_dir.exists():
            backup_dir = output_dir.with_name(f".{output_dir.name}-previous-{uuid.uuid4().hex}")
            output_dir.rename(backup_dir)
        try:
            temp_dir.rename(output_dir)
        except Exception:
            if backup_dir is not None and backup_dir.exists():
                backup_dir.rename(output_dir)
            raise
        if backup_dir is not None:
            shutil.rmtree(backup_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
