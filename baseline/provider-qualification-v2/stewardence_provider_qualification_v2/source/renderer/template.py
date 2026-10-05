from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from django.template import Context, Engine

TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "templates"
BRAND_LOGO_PATH = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "brand"
    / "stewardence-helix-orbit-light.png"
)
_ENGINE = Engine(dirs=(TEMPLATE_DIRECTORY,), autoescape=True, debug=False)


def render_report_html(payload: dict[str, Any]) -> str:
    template = _ENGINE.get_template("report.html")
    brand_logo_data_url = "data:image/png;base64," + base64.b64encode(
        BRAND_LOGO_PATH.read_bytes()
    ).decode("ascii")
    return template.render(
        Context(
            {
                "brand_logo_data_url": brand_logo_data_url,
                "report": payload,
            },
            autoescape=True,
            use_l10n=False,
            use_tz=False,
        )
    )
