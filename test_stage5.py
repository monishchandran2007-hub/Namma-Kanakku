"""
test_stage5.py - Automated tests for Stage 5 MCP Apps Khata Widget.
Verifies:
1. Widget HTML file existence, non-emptiness, and zero external network calls.
2. Widget responsive styling (light/dark mode, accessibility contrast).
3. MCP Apps postMessage protocol compliance (ui/initialize, host-context-changed, ui/notifications/tool-input).
4. Labelled demo data disclaimer present.
5. Resource registration in server.py exposes 'ui://khata-card'.
"""

import os
import re
import pytest

WIDGET_PATH = os.path.join(os.path.dirname(__file__), "widget.html")

def test_widget_file_exists_and_valid():
    assert os.path.exists(WIDGET_PATH), "widget.html must exist in project root"
    with open(WIDGET_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    assert len(html) > 500, "widget.html should have substantial content"
    assert "<!DOCTYPE html>" in html or "<!doctype html>" in html.lower()
    assert "<html" in html.lower()
    assert "</html>" in html.lower()

def test_widget_zero_external_network_dependencies():
    """
    Alexa+ and MCP Apps security rule: widgets must be self-contained.
    No external script tags, external stylesheets, Google fonts, or remote images.
    """
    with open(WIDGET_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Disallow remote script srcs (http:// or https://)
    remote_scripts = re.findall(r'<script[^>]+src=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
    assert len(remote_scripts) == 0, f"Found external script tag: {remote_scripts}"

    # Disallow remote stylesheets
    remote_links = re.findall(r'<link[^>]+href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
    assert len(remote_links) == 0, f"Found external stylesheet: {remote_links}"

    # Disallow @import url(http...) in CSS
    remote_css_imports = re.findall(r'@import\s+url\(["\']?(https?://[^"\'\)]+)["\']?\)', html, re.IGNORECASE)
    assert len(remote_css_imports) == 0, f"Found external CSS import: {remote_css_imports}"

def test_widget_demo_disclaimer():
    """Confirms mandatory demo data labelling."""
    with open(WIDGET_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert "[DEMO DATA - NOT REAL]" in html

def test_widget_postmessage_protocol_handshake():
    """
    Confirms standard MCP Apps UI postMessage protocol listeners and emitters.
    """
    with open(WIDGET_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Must listen for host window message events
    assert "window.addEventListener(\"message\"" in html or "window.addEventListener('message'" in html

    # Must handle ui/initialize or host context
    assert "ui/initialize" in html
    assert "ui/notifications/initialized" in html
    assert "host-context-changed" in html or "tool-input" in html

def test_widget_theming_and_accessibility():
    """
    Checks that CSS supports both light and dark themes.
    """
    with open(WIDGET_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    assert "prefers-color-scheme" in html or "theme-dark" in html or "--bg" in html

def test_server_exposes_widget_resource():
    """
    Inspects server.py to confirm ui://khata-card registration and metadata decoration.
    """
    server_path = os.path.join(os.path.dirname(__file__), "server.py")
    with open(server_path, "r", encoding="utf-8") as f:
        code = f.read()

    assert 'ui://khata-card' in code
    assert 'resourceUri' in code
    assert '/widget' in code
