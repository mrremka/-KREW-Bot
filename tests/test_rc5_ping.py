"""A live-code smoke signal to verify automated updates without revealing secrets."""
import tempfile
import unittest
from pathlib import Path
from krew.db import Database
from krew.core import BotCore, installed_version

class API:
    def __init__(self): self.calls=[]
    def call(self, method, **kwargs):
        self.calls.append((method,kwargs))
        if method == "sendMessage": return {"message_id": 1}
        return True

class PingSmokeTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db=Database(Path(self.dir.name)/"test.sqlite")
        self.addCleanup(self.db.close)
        self.api=API()
        self.bot=BotCore(self.api,self.db,"krew_test")
    def test_ping_private_reports_new_version(self):
        self.bot.on_message({"chat":{"id":23,"type":"private"},"from":{"id":23},"message_id":1,"text":"/ping"})
        self.assertEqual(installed_version(),"1.0.0-rc.9")
        message=[v for m,v in self.api.calls if m=="sendMessage"][-1]["text"]
        self.assertIn("Pong",message)
        self.assertIn("1.0.0-rc.9",message)
    def test_ping_does_not_change_user_subscriptions(self):
        self.bot.on_message({"chat":{"id":23,"type":"private"},"from":{"id":23},"message_id":1,"text":"/ping"})
        self.assertFalse(self.db.news_enabled(23))
    def test_ping_does_not_expose_secret_env(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"BOT_TOKEN":"private-test-secret"}):
            self.bot.on_message({"chat":{"id":23,"type":"private"},"from":{"id":23},"message_id":1,"text":"/ping"})
        message=[v for m,v in self.api.calls if m=="sendMessage"][-1]["text"]
        self.assertNotIn("private-test-secret",message)

if __name__ == "__main__": unittest.main()
