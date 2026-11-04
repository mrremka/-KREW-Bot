"""Control Center 2.0 assets: navigation, safe DOM and update compatibility."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'krew' / 'static'


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.nav = set()
        self.extra = set()
        self.buttons = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if 'id' in attributes:
            self.ids.add(attributes['id'])
        if tag == 'button' and 'data-page' in attributes:
            self.nav.add(attributes['data-page'])
        if tag == 'button' and 'data-extra-page' in attributes:
            self.extra.add(attributes['data-extra-page'])
        if tag == 'button' and 'id' in attributes:
            self.buttons.add(attributes['id'])


class ControlCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (BASE / 'index.html').read_text(encoding='utf8')
        cls.css = (BASE / 'style.css').read_text(encoding='utf8')
        cls.js = (BASE / 'app.js').read_text(encoding='utf8')
        cls.elements = Elements()
        cls.elements.feed(cls.html)

    def test_seven_existing_panels_are_present(self):
        self.assertEqual(self.elements.nav, {
            'overview', 'analytics', 'reports', 'settings',
            'rulesets', 'community', 'audit'
        })

    def test_mobile_more_menu_contains_secondary_panels(self):
        self.assertEqual(self.elements.extra, {'rulesets', 'community', 'audit'})
        self.assertTrue({'more-menu', 'more-button'}.issubset(self.elements.ids))

    def test_telegram_authorization_hooks_are_preserved(self):
        self.assertIn('Telegram.WebApp', self.js)
        self.assertIn('"Authorization":"tma "+initData', self.js)
        self.assertIn('if(!initData)', self.js)

    def test_client_renders_user_data_as_text_not_html(self):
        self.assertIn('n.textContent=String(txt)', self.js)
        self.assertNotIn('.innerHTML=', self.js)
        self.assertNotIn('document.write(', self.js)

    def test_action_calls_use_auth_api_and_no_direct_token(self):
        self.assertIn('async function api(path,method="GET",payload)', self.js)
        self.assertIn('await api(base()+"/settings","PATCH"', self.js)
        self.assertNotIn('BOT_TOKEN', self.js)

    def test_rapid_switches_cancel_stale_gets_not_mutations(self):
        self.assertIn('app.renderController.abort()', self.js)
        self.assertIn('method==="GET" && app.renderController', self.js)
        self.assertIn('controller===app.renderController', self.js)

    def test_analytics_has_three_live_metrics(self):
        for field in ('"messages","Сообщения"', '"joins","Вступления"', '"actions","Модерация"'):
            self.assertIn(field, self.js)
        self.assertIn('aria-pressed', self.js)

    def test_persistent_chat_selection_is_optional(self):
        self.assertIn('function restoredChat()', self.js)
        self.assertIn('function rememberChat(chat)', self.js)
        self.assertGreaterEqual(self.js.count('catch(_)'), 2)

    def test_destructive_report_action_requires_confirmation(self):
        self.assertIn('await confirmAction("Выдать предупреждение?"', self.js)
        self.assertNotIn('window.confirm(', self.js)

    def test_settings_limits_are_checked_before_mutations(self):
        self.assertIn('Number.isInteger(limit)', self.js)
        self.assertIn('Number.isInteger(mentionsLimit)', self.js)

    def test_telegram_mobile_support(self):
        self.assertIn('viewport-fit=cover', self.html)
        self.assertIn('env(safe-area-inset-bottom)', self.css)
        self.assertIn('@media(max-width:640px)', self.css)
        self.assertIn('prefers-reduced-motion', self.css)

    def test_accessibility(self):
        self.assertTrue({'content', 'notice', 'refresh-button', 'navigation', 'heading'}.issubset(self.elements.ids))
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('aria-expanded="false"', self.html)
        self.assertIn('role","alertdialog"', self.js)

    def test_static_assets_use_no_external_frontend_framework(self):
        self.assertRegex(self.html, r'<script[^>]* src="app\.js"')
        self.assertNotIn('cdn.jsdelivr.net', self.html)
        self.assertNotIn('unpkg.com', self.html)
        self.assertNotIn('@import', self.css)


if __name__ == '__main__':
    unittest.main()
