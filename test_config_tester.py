import unittest
from unittest.mock import call, patch

from config_tester import print_test_summary, test_all_configs


class ConfigTesterTests(unittest.TestCase):
    def test_summary_selects_lowest_latency_success(self):
        results = [
            {"config": "slow", "success": True, "latency": 312.9, "message": "ok"},
            {"config": "fast", "success": True, "latency": 101.2, "message": "ok"},
            {"config": "failed", "success": False, "latency": 0, "message": "error"},
        ]

        self.assertEqual(print_test_summary(results), "fast")

    @patch("config_tester.run_hysteria_test", return_value=(True, 100.0, "ok"))
    @patch("config_tester.find_config_files")
    def test_quiet_flag_is_passed_to_config_tests(self, find_configs, run_test):
        find_configs.return_value = ["/tmp/slow.yaml", "/tmp/fast.yaml"]
        test_urls = ["https://example.com"]

        test_all_configs("/tmp", test_urls=test_urls, quiet=True)

        self.assertEqual(
            run_test.call_args_list,
            [
                call("/tmp/slow.yaml", 1080, test_urls, quiet=True),
                call("/tmp/fast.yaml", 1081, test_urls, quiet=True),
            ],
        )


if __name__ == "__main__":
    unittest.main()
