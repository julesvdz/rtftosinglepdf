"""
modules/config_manager.py
-------------------------
Handles JSON persistence for all UI-controlled parameters.

Save: writes config.json alongside the final PDF with an ISO 8601 UTC
      timestamp for audit purposes.
Load: reads a previously saved config.json and returns a plain dict
      that Flask sends back to the UI for field re-population.

JSON schema (all keys):
{
    "timestamp":            "2026-02-23T13:20:00Z",
    "rtf_directory":        "C:/data/rtf",
    "output_directory":     "C:/data/output",
    "csv_path":             "",
    "header": {
        "left":   "",
        "center": "CONFIDENTIAL",
        "right":  "Study ABC"
    },
    "footer": {
        "left":   "2026-02-23",
        "center": "",
        "right":  ""
    },
    "header_y_pts":         30,
    "footer_y_pts":         820,
    "page_number_x":        540,
    "page_number_y":        818,
    "page_number_font_size": 8
}
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import config as _defaults


# ---------------------------------------------------------------------------
# Schema / defaults
# ---------------------------------------------------------------------------

def _default_config() -> dict:
    return {
        "timestamp": "",
        "rtf_directory": "",
        "output_directory": "",
        "csv_path": "",
        "header": {"left": "", "center": "", "right": ""},
        "footer": {"left": "", "center": "", "right": ""},
        "header_top_margin_pts":         _defaults.HEADER_TOP_MARGIN,
        "footer_bottom_margin_pts":      _defaults.FOOTER_BOTTOM_MARGIN,
        "page_number_bottom_margin_pts": _defaults.PAGE_NUMBER_BOTTOM_MARGIN,
        "page_number_right_margin_pts":  _defaults.PAGE_NUMBER_RIGHT_MARGIN,
        "page_number_font_size":         _defaults.PAGE_NUMBER_FONT_SIZE,
        # Run output references (populated at job start once filenames are known)
        "output_pdf_filename":    "",
        "log_filename":           "",
        "config_filename":        "",
        "csv_original_filename":  "",
        "max_workers": _defaults.MAX_PARALLEL_CONVERSIONS,
        "toc_landscape": False,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_config(
    params: dict,
    output_dir: str | Path,
    filename_stem: str = "config",
) -> Path:
    """Persist all UI parameters to a JSON file in *output_dir*.

    A fresh ISO 8601 UTC timestamp is injected automatically; any caller-
    supplied ``"timestamp"`` key is silently overwritten.

    Parameters
    ----------
    params:
        Dict of UI parameter values (see schema above).
    output_dir:
        Directory where the file will be written (created if missing).
    filename_stem:
        Stem used for the output file name.  The final name will be
        ``<filename_stem>.json``.  Defaults to ``"config"``.

    Returns
    -------
    Path
        Absolute path to the written JSON file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = _default_config()
    payload.update(params)
    payload["timestamp"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    config_path = output_dir / f"{filename_stem}.json"
    with config_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    return config_path


def load_config(config_path: str | Path) -> dict:
    """Load a previously saved config.json and return it as a plain dict.

    Missing keys are back-filled with defaults so the UI always receives a
    complete structure even when loading older config files.

    Parameters
    ----------
    config_path:
        Path to the JSON file to load.

    Returns
    -------
    dict
        Merged config with all keys present.

    Raises
    ------
    FileNotFoundError
        When the file does not exist.
    ValueError
        When the file contains invalid JSON.
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with config_path.open("r", encoding="utf-8") as fh:
            loaded: dict = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file: {exc}") from exc

    # Back-fill defaults for keys added in future versions
    base = _default_config()
    base.update(loaded)

    # Migrate old absolute-coordinate keys (pre page-size-adaptation) to the
    # new margin-from-edge keys.  A4 dimensions (842 × 595 pts) are used as
    # the reference since all old configs were produced against A4 defaults.
    _A4_H, _A4_W = 842.0, 595.0
    if "footer_bottom_margin_pts" not in loaded and "footer_y_pts" in loaded:
        base["footer_bottom_margin_pts"] = max(5.0, _A4_H - float(loaded["footer_y_pts"]))
    if "page_number_bottom_margin_pts" not in loaded and "page_number_y" in loaded:
        base["page_number_bottom_margin_pts"] = max(5.0, _A4_H - float(loaded["page_number_y"]))
    if "page_number_right_margin_pts" not in loaded and "page_number_x" in loaded:
        base["page_number_right_margin_pts"] = max(5.0, _A4_W - float(loaded["page_number_x"]))
    if "header_top_margin_pts" not in loaded and "header_y_pts" in loaded:
        base["header_top_margin_pts"] = float(loaded["header_y_pts"])

    return base


def build_params_from_form(form: dict) -> dict:
    """Convert a Flask request.form dict into the canonical config structure.

    Parameters
    ----------
    form:
        Flat key-value dict from the HTML form (e.g. ``request.form``).

    Returns
    -------
    dict
        Canonical config dict ready to pass to :func:`save_config`.
    """
    def _float(key: str, default: float) -> float:
        try:
            return float(form.get(key, default))
        except (ValueError, TypeError):
            return default

    def _int(key: str, default: int) -> int:
        try:
            return int(form.get(key, default))
        except (ValueError, TypeError):
            return default

    return {
        "rtf_directory": form.get("rtf_directory", "").strip(),
        "output_directory": form.get("output_directory", "").strip(),
        "csv_path": form.get("csv_path", "").strip(),
        "header": {
            "left":   form.get("header_left", "").strip(),
            "center": form.get("header_center", "").strip(),
            "right":  form.get("header_right", "").strip(),
        },
        "footer": {
            "left":   form.get("footer_left", "").strip(),
            "center": form.get("footer_center", "").strip(),
            "right":  form.get("footer_right", "").strip(),
        },
        "header_top_margin_pts":         _float("header_top_margin_pts",         _defaults.HEADER_TOP_MARGIN),
        "footer_bottom_margin_pts":      _float("footer_bottom_margin_pts",      _defaults.FOOTER_BOTTOM_MARGIN),
        "page_number_bottom_margin_pts": _float("page_number_bottom_margin_pts", _defaults.PAGE_NUMBER_BOTTOM_MARGIN),
        "page_number_right_margin_pts":  _float("page_number_right_margin_pts",  _defaults.PAGE_NUMBER_RIGHT_MARGIN),
        "page_number_font_size": _int(
            "page_number_font_size", _defaults.PAGE_NUMBER_FONT_SIZE
        ),
        "max_workers": _int("max_workers", _defaults.MAX_PARALLEL_CONVERSIONS),
        "toc_landscape": form.get("toc_landscape") in ("1", "true", "on", "True", True),
    }
