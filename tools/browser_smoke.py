#!/usr/bin/env python3
"""Optional post-deployment browser smoke test. pip install playwright; playwright install chromium."""
import sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

if len(sys.argv) != 2 or urlparse(sys.argv[1]).scheme not in ('http','https'):
    raise SystemExit('Usage: python tools/browser_smoke.py https://YOUR-PROOFCHECK-DOMAIN/')
url = sys.argv[1]
if not urlparse(url).hostname in ('localhost','127.0.0.1') and not url.startswith('https://'):
    raise SystemExit('Public site MUST use HTTPS')

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(locale='ar-SA')
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=25000)
        page.locator('#welcomeGate').wait_for(state='visible', timeout=15000)
        assert page.evaluate("localStorage.getItem('proofcheck_session')") is None
        page.locator('#acceptStorage').check()
        page.locator('#startScan').click()
        page.wait_for_function("localStorage.getItem('proofcheck_session') !== null", timeout=15000)
        page.locator('[data-tab="tests"]').click()
        page.locator('#runCpu').click()
        page.wait_for_function("document.querySelector('#benchmarkResults').textContent.includes('JavaScript:')", timeout=18000)
        page.locator('#runMemory').click()
        page.wait_for_function("document.querySelector('#benchmarkResults').textContent.includes('ذاكرة متصفح')", timeout=18000)
        page.locator('#runDisk').click()
        page.wait_for_function("document.querySelector('#benchmarkResults').textContent.includes('IndexedDB')", timeout=18000)
        page.locator('[data-tab="reports"]').click()
        page.locator('#createShare').click()
        page.locator('#copyShare').wait_for(state='visible', timeout=15000)
        assert not errors, 'JavaScript errors: ' + str(errors)
        print('PASS: consent, session, browser benchmarks, report sharing')
    finally:
        if page.locator('#deleteSession').is_visible():
            page.on('dialog', lambda d: d.accept())
            page.locator('#deleteSession').click()
        browser.close()
