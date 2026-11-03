"""Regression tests: Cloudflare Mini App logs must not leak signed URLs."""
import unittest
from unittest.mock import Mock, patch
from krew.web import Handler


class MiniAppPrivacyTests(unittest.TestCase):
    def handler(self, method="GET"):
        handler = object.__new__(Handler)
        handler.command = method
        return handler

    def test_access_log_does_not_include_sensitive_url(self):
        h = self.handler()
        private_request = 'GET /?data=HIDDEN_VALUE&q=SENSITIVE_VALUE HTTP/1.1'
        with patch('krew.web.LOG.info') as info:
            h.log_message('"%s" %s %s', private_request, '200', '128')
        self.assertEqual(info.call_args.args, ('HTTP %s response=%s', 'GET', '200'))
        self.assertNotIn('HIDDEN_VALUE', str(info.call_args))
        self.assertNotIn('SENSITIVE_VALUE', str(info.call_args))

    def test_errors_do_not_log_attacker_supplied_text(self):
        h = self.handler('POST')
        with patch('krew.web.LOG.info') as info:
            h.log_message('code %d, message %s', 400, 'field=LEAKME')
        self.assertEqual(info.call_args.args, ('HTTP %s response=%s', 'POST', 'unknown'))
        self.assertNotIn('LEAKME', str(info.call_args))

    def test_unknown_method_is_not_echoed(self):
        h = self.handler('SENSITIVE_VALUE_TOKEN')
        with patch('krew.web.LOG.info') as info:
            h.log_message('"%s" %s %s', 'SENSITIVE_VALUE_TOKEN / HTTP/1.1', '404', '-')
        self.assertEqual(info.call_args.args, ('HTTP %s response=%s', 'OTHER', '404'))

    def test_health_endpoint_still_works_without_auth(self):
        h = self.handler()
        h.path = '/health?token=SENSITIVE_VALUE'
        h._write = Mock()
        h._handle('GET')
        h._write.assert_called_once_with(200, b'{"status":"ok"}')

if __name__ == '__main__':
    unittest.main()
