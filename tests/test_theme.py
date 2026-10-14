"""Theme must match the Jira Command Library prototype."""
import re
from pathlib import Path

from services.preference_service import DARK_TOKENS, DEFAULTS, LIGHT_TOKENS, ALLOWED_FONTS, preference_css

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
PROTOTYPE = {"bg": "#f0f4fb", "bg2": "#ffffff", "bg3": "#e8edf8", "sb": "#0c1f6e", "border": "#dde3f0",
             "text": "#111827", "text2": "#4b5675", "text3": "#8898b8"}
PROTOTYPE_DARK = {"bg": "#0b0f1c", "bg2": "#111827", "bg3": "#1a2236", "sb": "#060d1f", "border": "#1e2d48",
                  "text": "#e2e8f4", "text2": "#8898b8"}


def test_light_tokens_match_prototype():
    for name, value in PROTOTYPE.items():
        assert LIGHT_TOKENS[name] == value


def test_dark_tokens_match_prototype():
    for name, value in PROTOTYPE_DARK.items():
        assert DARK_TOKENS[name] == value


def test_prototype_is_default_theme():
    assert DEFAULTS["theme"] == "light" and DEFAULTS["accent_color"] == "#0c46ce" and DEFAULTS["font_family"] == "DM Sans"


def test_stylesheet_has_no_angle_brackets():
    # st.html runs DOMPurify: a stray "<x>" in a comment makes it drop the whole sheet.
    assert "<" not in CSS


def test_fonts_are_self_hosted_and_present():
    assert "googleapis" not in CSS
    for font in re.findall(r"url\('app/static/fonts/([^']+)'\)", CSS):
        assert (ROOT / "static" / "fonts" / font).exists(), font
    for family in ("Syne", "DM Sans", "IBM Plex Mono"):
        assert f"font-family: '{family}'" in CSS


def test_no_legacy_palette():
    for old in ("#0F172A", "#0f172a", "#9aa9c4", "#27344d", "#0b1220"):
        assert old not in CSS


def test_css_uses_tokens_not_hardcoded_surfaces():
    assert "var(--bg2)" in CSS and "var(--sb)" in CSS and "var(--border)" in CSS


def test_dark_and_system_modes():
    dark = preference_css({"theme": "dark"})
    assert "#0b0f1c" in dark and "prefers-color-scheme" not in dark
    system = preference_css({"theme": "system"})
    assert "prefers-color-scheme: dark" in system and "#f0f4fb" in system


def test_invalid_values_fall_back_safely():
    css = preference_css({"accent_color": "red;}</style><script>", "font_family": "Evil'; x", "theme": "neon"})
    assert "<script>" not in css and "Evil" not in css and "#0c46ce" in css and "#f0f4fb" in css


def test_body_font_choices_keep_brand_fonts():
    assert "DM Sans" in ALLOWED_FONTS
    assert "Syne" not in preference_css({"font_family": "Arial"}).split("--sans:")[1].split(";")[0]
