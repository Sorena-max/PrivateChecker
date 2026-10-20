import json
import os
import tempfile
import unittest

from privatechecker import config
from tests.helpers import FRIEND, OWNER, STRANGER, make_config


class NormalizeTests(unittest.TestCase):
    def test_defaults_fill_everything(self):
        cfg = config.normalize({})
        self.assertEqual(cfg["interval_min"], 30)
        self.assertEqual(set(cfg["sections"]), set(config.SECTIONS))
        self.assertTrue(cfg["alerts"]["enabled"])

    def test_interval_is_clamped_to_5_1200(self):
        self.assertEqual(config.normalize({"interval_min": 1})["interval_min"], 5)
        self.assertEqual(config.normalize({"interval_min": 99999})["interval_min"], 1200)
        self.assertEqual(config.normalize({"interval_min": "abc"})["interval_min"], 30)

    def test_valid_interval_bounds(self):
        self.assertTrue(config.valid_interval(5))
        self.assertTrue(config.valid_interval("1200"))
        self.assertFalse(config.valid_interval(4))
        self.assertFalse(config.valid_interval(1201))
        self.assertFalse(config.valid_interval("x"))

    def test_users_are_deduped_and_exclude_owner(self):
        cfg = config.normalize({"owner_id": 5, "users": [5, 7, 7, "8", "bad", -1, 0]})
        self.assertEqual(cfg["users"], [7, 8])

    def test_invalid_language_falls_back(self):
        self.assertEqual(config.normalize({"language": "xx"})["language"], "fa")

    def test_service_names_are_validated(self):
        cfg = config.normalize({"services": ["nginx", "bad name", "a;b", "x-ui", "nginx"]})
        self.assertEqual(cfg["services"], ["nginx", "x-ui"])

    def test_alert_thresholds_are_bounded(self):
        cfg = config.normalize({"alerts": {"cpu": 10, "mem": 500, "disk": "x"}})
        self.assertEqual((cfg["alerts"]["cpu"], cfg["alerts"]["mem"], cfg["alerts"]["disk"]),
                         (50, 99, 90))

    def test_iran_ports_are_limited_and_validated(self):
        cfg = config.normalize({"iran": {"tcp_ports": [443, 443, 0, 70000, 80, 22, 8080]}})
        self.assertEqual(cfg["iran"]["tcp_ports"], [443, 80, 22])

    def test_unknown_keys_are_dropped(self):
        self.assertNotIn("evil", config.normalize({"evil": 1}))


class StoreTests(unittest.TestCase):
    def test_roundtrip_and_permissions(self):
        cfg, _ = make_config(interval_min=45)
        reopened = config.open_config(cfg.path)
        self.assertEqual(reopened.snapshot()["interval_min"], 45)
        if os.name == "posix":
            self.assertEqual(os.stat(cfg.path).st_mode & 0o777, 0o600)

    def test_corrupt_file_falls_back_to_defaults(self):
        path = os.path.join(tempfile.mkdtemp(), "config.json")
        with open(path, "w") as fh:
            fh.write("{not json")
        self.assertEqual(config.open_config(path).snapshot()["interval_min"], 30)

    def test_save_is_valid_json(self):
        cfg, _ = make_config()
        with open(cfg.path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["owner_id"], OWNER)


class AuthTests(unittest.TestCase):
    def test_only_owner_and_added_users(self):
        cfg, _ = make_config(users=[FRIEND])
        data = cfg.snapshot()
        self.assertTrue(config.is_authorized(data, OWNER))
        self.assertTrue(config.is_authorized(data, FRIEND))
        self.assertFalse(config.is_authorized(data, STRANGER))
        self.assertFalse(config.is_authorized(data, None))
        self.assertFalse(config.is_authorized(data, 0))

    def test_recipients_list_owner_first(self):
        cfg, _ = make_config(users=[FRIEND])
        self.assertEqual(config.recipients(cfg.snapshot()), [OWNER, FRIEND])


if __name__ == "__main__":
    unittest.main()
