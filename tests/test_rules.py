import unittest
from krew.rules import FloodGuard, clean_word, contains_blocked_word, has_link
from krew.core import level, parse_duration

class RulesTests(unittest.TestCase):
    def test_detects_links(self):
        for item in ('https://example.com/x', 't.me/somegroup', 'example.ru', 'WWW.TEST.ORG'):
            self.assertTrue(has_link(item))
        self.assertFalse(has_link('Привет! Начался урок 3.14'))
        self.assertTrue(has_link('текст', [{'type': 'text_link', 'url': 'https://evil.net'}]))

    def test_blocked_words_use_boundaries(self):
        self.assertEqual(contains_blocked_word('Очень плохое слово!', ['плохое слово']), 'плохое слово')
        self.assertIsNone(contains_blocked_word('котик', ['кот']))
        self.assertEqual(clean_word('  СЛОВО  '), 'слово')
        with self.assertRaises(ValueError):
            clean_word('а')

    def test_flood_and_repeats(self):
        f = FloodGuard(limit=3, window=8)
        self.assertIsNone(f.check(-100, 1, 'a', now=1))
        self.assertIsNone(f.check(-100, 1, 'b', now=2))
        self.assertIsNone(f.check(-100, 1, 'c', now=3))
        self.assertEqual(f.check(-100, 1, 'd', now=4), 'Слишком много сообщений подряд')
        self.assertIsNone(f.check(-100, 2, 'одинаково', now=10))
        self.assertIsNone(f.check(-100, 2, 'одинаково', now=11))
        self.assertEqual(f.check(-100, 2, 'одинаково', now=12), 'Повторяющиеся сообщения')

    def test_duration_and_level(self):
        self.assertEqual(parse_duration('10m причина'), (600, 'причина'))
        self.assertEqual(parse_duration('2h')[0], 7200)
        for invalid in ('0m', '10w', 'spam', '366d', ''):
            with self.assertRaises(ValueError):
                parse_duration(invalid)
        self.assertEqual(level(0), 1)
        self.assertGreater(level(600), 1)

if __name__ == '__main__':
    unittest.main()
