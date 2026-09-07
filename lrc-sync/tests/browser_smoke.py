#!/usr/bin/env python3
"""Local HTML interaction checks using the project's synthetic 12-second demo."""
import argparse
import json
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    passed, errors, requests = [], [], []
    with sync_playwright() as pw:
        opts = {'headless': True, 'args': ['--no-sandbox', '--autoplay-policy=no-user-gesture-required']}
        binary = shutil.which('chromium')
        if binary: opts['executable_path'] = binary
        browser = pw.chromium.launch(**opts)
        page = browser.new_page(viewport={'width': 1280, 'height': 1100}, accept_downloads=True)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: requests.append(r.url))
        page.on('dialog', lambda dialog: dialog.accept())
        page.set_content(args.page.read_text(encoding='utf-8'), wait_until='domcontentloaded')
        assert page.locator('#rows tr').count() == 5
        assert '提示音' in page.locator('#title').inner_text()
        passed.append('render')

        page.locator('#audioFile').set_input_files(str(args.audio.resolve()))
        page.wait_for_function('() => audioOK === true', timeout=15000)
        assert abs(page.evaluate('audio.duration') - 12) < .01
        passed.append('local_audio')

        page.locator('#rows tr').nth(1).click()
        page.locator('#later').click()
        assert page.locator('#editTime').input_value() == '00:01.10'
        passed.append('single_line_nudge')

        page.locator('summary').click()
        page.locator('#undo').click()
        assert page.locator('#editTime').input_value() == '00:01.00'
        passed.append('undo')

        before = page.evaluate('JSON.stringify(project.entries)')
        page.locator('#allEarlier').click()
        assert '超出' in page.locator('#status').inner_text()
        assert page.evaluate('JSON.stringify(project.entries)') == before
        passed.append('reject_out_of_bounds')

        page.locator('#reviewed').click()
        assert page.evaluate('project.entries[1].verified') is True
        page.locator('#later').click()
        assert page.evaluate('project.entries[1].verified') is False
        passed.append('verification_invalidated_on_edit')

        with page.expect_download() as download:
            page.locator('#saveProject').click()
        saved = args.out_dir / 'saved.project.json'
        download.value.save_as(saved)
        assert json.loads(saved.read_text(encoding='utf-8'))['entries'][1]['time'] == 1.1
        page.locator('#later').click()
        page.locator('#projectFile').set_input_files(str(saved.resolve()))
        page.wait_for_function('() => project.entries[1].time === 1.1')
        passed.append('save_and_restore_project')

        with page.expect_download() as download:
            page.locator('#exportTop').click()
        lrc = args.out_dir / 'exported.lrc'
        download.value.save_as(lrc)
        assert lrc.read_bytes().startswith(b'\xef\xbb\xbf')
        assert '[00:01.10]第一声提示音' in lrc.read_text(encoding='utf-8-sig')
        passed.append('lrc_download')

        page.evaluate('audio.currentTime = 4.2')
        page.wait_for_function("() => document.getElementById('lyricNow').textContent === '第二声提示音'")
        page.locator('#speed').select_option('0.75')
        assert page.evaluate('audio.playbackRate') == .75
        passed.append('playback_highlight_and_speed')

        page.locator('#rows tr').nth(3).click()
        page.evaluate('audio.currentTime = 7.8')
        page.locator('#addBlank').click()
        assert page.locator('#rows tr').count() == 6
        page.locator('#deleteBlank').click()
        assert page.locator('#rows tr').count() == 5
        passed.append('clear_cue_insert_delete')

        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.out_dir / 'mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1280, 'height': 1100})
        page.screenshot(path=str(args.out_dir / 'desktop.png'), full_page=True)
        passed.append('mobile_layout')

        assert not errors, errors
        external = [u for u in requests if u.startswith(('http://', 'https://'))]
        assert not external, external
        passed.append('no_page_errors_or_external_requests')
        browser.close()
    report = {'passed': len(passed), 'checks': passed,
              'scope': 'Synthetic audio only; HTML injected into a blank browser page. Not a test of real-song alignment, every codec, or file-origin storage.'}
    (args.out_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
