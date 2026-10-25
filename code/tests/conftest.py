"""Shared pytest configuration. Registers the `live_ai` marker (Phase 4
task 6): a test marked `@pytest.mark.live_ai` needs a real model call
and is skipped by default so the whole suite never needs API keys;
pass `--run-live-ai` to actually run them.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-ai", action="store_true", default=False,
        help="Run tests marked live_ai (makes real Groq/Gemini calls; needs API keys).",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live_ai: needs a real model call; skipped unless --run-live-ai is passed")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live-ai"):
        return
    skip_live = pytest.mark.skip(reason="needs --run-live-ai")
    for item in items:
        if "live_ai" in item.keywords:
            item.add_marker(skip_live)
