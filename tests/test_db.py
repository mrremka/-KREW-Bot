import tempfile
import unittest
from pathlib import Path
from krew.db import Database

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'test.db')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_chats_independent(self):
        a = self.db.get_chat(-100)
        b = self.db.get_chat(-200)
        self.assertTrue(a['antispam'])
        self.assertFalse(a['antilinks'])
        self.db.toggle(-100, 'antilinks')
        self.assertTrue(self.db.get_chat(-100)['antilinks'])
        self.assertFalse(self.db.get_chat(-200)['antilinks'])
        with self.assertRaises(ValueError):
            self.db.toggle(-100, 'chat_id')

    def test_warnings(self):
        self.assertEqual(self.db.warn(-1, 11), 1)
        self.assertEqual(self.db.warn(-1, 11), 2)
        self.assertEqual(self.db.get_warn(-2, 11), 0)
        self.assertEqual(self.db.un_warn(-1, 11), 1)
        self.db.reset_warn(-1, 11)
        self.assertEqual(self.db.get_warn(-1, 11), 0)

    def test_xp_activity_cooldown(self):
        self.assertTrue(self.db.activity(-1, 11, 'Иван', now=100))
        self.assertFalse(self.db.activity(-1, 11, 'Иван', now=110))
        self.assertTrue(self.db.activity(-1, 11, 'Иван', now=161))
        p = self.db.profile(-1, 11)
        self.assertEqual(p['messages'], 3)
        self.assertGreater(p['xp'], 10)

    def test_daily_once_per_utc_day(self):
        self.assertEqual(self.db.daily(-1, 11, 'Иван', 30, '2026-11-03'), (True, 30))
        self.assertEqual(self.db.daily(-1, 11, 'Иван', 40, '2026-11-03'), (False, 30))
        self.assertEqual(self.db.daily(-1, 11, 'Иван', 35, '2026-11-04'), (True, 65))

    def test_quiz_award_once_and_same_group(self):
        quiz = self.db.new_quiz(-1, 2)
        self.assertEqual(self.db.answer_quiz(quiz, -2, 11, 2), 'not_found')
        self.assertEqual(self.db.answer_quiz(quiz, -1, 11, 2), 'correct')
        self.assertEqual(self.db.answer_quiz(quiz, -1, 11, 2), 'already')
        self.assertEqual(self.db.profile(-1, 11)['coins'], 15)
        self.assertIsNone(self.db.new_quiz(-1, 2))

    def test_badge_shop_purchase_and_equip(self):
        self.assertEqual(self.db.buy_badge(-1, 11, 'crown', 500), 'insufficient')
        self.db.add_coins(-1, 11, 520)
        self.assertEqual(self.db.buy_badge(-1, 11, 'crown', 500), 'purchased')
        self.assertEqual(self.db.profile(-1, 11)['coins'], 20)
        self.assertEqual(self.db.buy_badge(-1, 11, 'crown', 500), 'equipped')
        self.assertEqual(self.db.profile(-1, 11)['coins'], 20)
        self.assertEqual(self.db.owned_badges(-1, 11), ['crown'])

    def test_word_management(self):
        self.assertTrue(self.db.add_word(-1, 'спам'))
        self.assertFalse(self.db.add_word(-1, 'спам'))
        self.assertEqual(self.db.list_words(-1), ['спам'])
        self.assertFalse(self.db.remove_word(-2, 'спам'))
        self.assertTrue(self.db.remove_word(-1, 'спам'))

if __name__ == '__main__':
    unittest.main()
