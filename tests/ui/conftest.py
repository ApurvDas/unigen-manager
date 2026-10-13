"""One Playwright session for every UI test file (two concurrent sync sessions are not allowed)."""
import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        yield b
        b.close()
