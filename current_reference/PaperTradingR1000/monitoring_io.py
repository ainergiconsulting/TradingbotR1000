# monitoring_io.py

from datetime import datetime, timezone
import json
from pathlib import Path


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def atomic_write_json(path: Path, data: dict) -> None:
    """Write runtime JSON state.

    These files are operational telemetry/control-plane state.  Direct writes
    are used because Windows can intermittently deny the temporary files used
    by atomic replace in this project directory.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2)
    try:
        path.write_text(content, encoding="utf-8")
    except PermissionError:
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
