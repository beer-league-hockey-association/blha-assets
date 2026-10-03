import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blha.fantrax import Fantrax, FantraxError  # noqa: E402


class Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, body):
        self.body, self.calls = body, []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return Resp(self.body)


def client(body):
    fx = Fantrax("abc")
    fx.session = FakeSession(body)
    return fx


class FantraxClientTests(unittest.TestCase):
    def test_error_body_raises(self):
        with self.assertRaises(FantraxError):
            client({"error": {"msg": "nope"}}).draft_picks()

    def test_period_param(self):
        fx = client({"rosters": {}})
        fx.rosters(5)
        self.assertEqual(fx.session.calls[0][1], {"leagueId": "abc", "period": 5})

    def test_rosters_default_has_no_period(self):
        fx = client({})
        fx.rosters()
        self.assertNotIn("period", fx.session.calls[0][1])

    def test_endpoints(self):
        fx = client([])
        fx.draft_picks(); fx.draft_results(); fx.adp()
        self.assertEqual([c[0].rsplit("/", 1)[1] for c in fx.session.calls],
                         ["getDraftPicks", "getDraftResults", "getAdp"])


if __name__ == "__main__":
    unittest.main()
