import os
import tempfile
import time
import unittest
from unittest import mock

from privatechecker import collectors

MEMINFO = """MemTotal:        2048000 kB
MemFree:          100000 kB
MemAvailable:    1024000 kB
SwapTotal:       1000000 kB
SwapFree:         750000 kB
"""

STAT_A = "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 1 1 1\n"
STAT_B = "cpu  150 0 150 900 0 0 0 0 0 0\ncpu0 1 1 1 1\n"

NET_DEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 5000 10 0 0 0 0 0 0 5000 10 0 0 0 0 0 0
  eth0: 1000000 100 0 0 0 0 0 0 2000000 100 0 0 0 0 0 0
 docker0: 777 1 0 0 0 0 0 0 777 1 0 0 0 0 0 0
"""

TCP = """  sl  local_address rem_address   st tx_queue rx_queue
   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0
   1: 0100007F:1538 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0
   2: 0A00000A:01BB 0B00000B:C350 01 00000000:00000000 00:00000000 00000000     0
"""

SSH_LOG = """Oct 20 10:00:01 host sshd[1]: Failed password for root from 198.51.100.7 port 4000 ssh2
Oct 20 10:00:02 host sshd[1]: Failed password for invalid user admin from 198.51.100.7 port 4001 ssh2
Oct 20 10:00:03 host sshd[2]: Invalid user test from 203.0.113.9 port 5000
Oct 20 10:05:00 host sshd[3]: Accepted publickey for deploy from 192.0.2.10 port 6000 ssh2: RSA
Oct 20 10:06:00 host cron[4]: unrelated line
"""


class ParserTests(unittest.TestCase):
    def test_meminfo(self):
        mem = collectors.parse_meminfo(MEMINFO)
        self.assertEqual(mem["total"], 2048000 * 1024)
        self.assertAlmostEqual(mem["pct"], 50.0)
        self.assertAlmostEqual(mem["swap_pct"], 25.0)

    def test_meminfo_garbage(self):
        self.assertIsNone(collectors.parse_meminfo("nonsense"))
        self.assertIsNone(collectors.parse_meminfo(None))

    def test_cpu_percent(self):
        a = collectors.parse_cpu_times(STAT_A)
        b = collectors.parse_cpu_times(STAT_B)
        # delta: busy 100 of 200 total -> 50 %
        self.assertAlmostEqual(collectors.cpu_percent(a, b), 50.0)
        self.assertIsNone(collectors.cpu_percent(a, a))
        self.assertIsNone(collectors.cpu_percent(None, b))

    def test_net_dev_skips_loopback_and_docker(self):
        parsed = collectors.parse_net_dev(NET_DEV)
        self.assertEqual(parsed, {"eth0": (1000000, 2000000)})

    def test_tcp_table(self):
        listening, established = collectors.parse_tcp_table(TCP)
        self.assertEqual(established, 1)
        self.assertIn((22, "public"), listening)
        self.assertIn((0x1538, "local"), listening)

    def test_ssh_log(self):
        res = collectors.parse_ssh_log(SSH_LOG)
        self.assertEqual(res["failed"], 3)
        self.assertEqual(res["top"][0], ("198.51.100.7", 2))
        self.assertEqual(res["accepted_count"], 1)
        self.assertEqual(res["accepted"][0]["user"], "deploy")

    def test_stat_line_with_spaces_in_name(self):
        line = "42 (my proc (x)) S 1 1 1 0 -1 0 0 0 0 0 10 5 0 0 20 0 1 0 100 0 0"
        name, ticks = collectors.parse_stat_line(line)
        self.assertEqual(name, "my proc (x)")
        self.assertEqual(ticks, 15)


class FakeProcTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "net"))
        files = {"meminfo": MEMINFO, "stat": STAT_A, "uptime": "90061.5 1000.0\n",
                 "net/dev": NET_DEV, "net/tcp": TCP, "net/tcp6": ""}
        for name, text in files.items():
            with open(os.path.join(self.root, name), "w") as fh:
                fh.write(text)
        patcher = mock.patch.dict(os.environ, {"SC_PROC": self.root})
        patcher.start()
        self.addCleanup(patcher.stop)

    def collector(self):
        col = collectors.Collector()
        col._ip = ("203.0.113.5", time.time())  # avoid any network access
        return col

    def test_uptime_and_memory(self):
        col = self.collector()
        self.assertEqual(int(collectors.uptime_seconds()), 90061)
        self.assertAlmostEqual(col.memory()["pct"], 50.0)

    def test_network_counts_and_rate(self):
        col = self.collector()
        first = col.network()
        self.assertEqual(first["rx_total"], 1000000)
        self.assertEqual(first["established"], 1)
        self.assertIsNone(first["rate"])
        second = col.network()
        self.assertIsNotNone(second["rate"])
        self.assertEqual(second["public_ip"], "203.0.113.5")

    def test_ports_prefers_public_scope(self):
        col = self.collector()
        listening, _ = collectors.parse_tcp_table(TCP)
        ports = col.ports(listening + [(22, "local")])
        self.assertIn((22, "public"), ports)

    def test_collect_only_one_section(self):
        col = self.collector()
        data = col.collect({"sections": {}, "services": [], "iran": {}}, only="memory")
        self.assertEqual(list(data), ["memory"])

    def test_missing_proc_does_not_crash(self):
        with mock.patch.dict(os.environ, {"SC_PROC": os.path.join(self.root, "nope")}):
            col = self.collector()
            self.assertIsNone(col.memory())
            self.assertEqual(col.network()["rx_total"], 0)
            self.assertEqual(col.disk(), [])


if __name__ == "__main__":
    unittest.main()
