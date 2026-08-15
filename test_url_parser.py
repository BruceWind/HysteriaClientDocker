import unittest

import yaml

from url_parser import parse_hysteria_url


class ParseHysteriaUrlTests(unittest.TestCase):
    def test_parses_salamander_obfs_password(self):
        url = (
            "hysteria2://cTSM0JGHim@168.107.49.85:54655?"
            "peer=go.microsoft.com&insecure=1&obfs=salamander&"
            "obfs-password=adfdafsdfdsfdsf#OC1-%E6%8A%97%E4%B8%A2%E5%8C%85"
        )

        config = parse_hysteria_url(url)

        self.assertEqual(
            config["obfs"],
            {
                "type": "salamander",
                "salamander": {"password": "adfdafsdfdsfdsf"},
            },
        )
        self.assertEqual(config["name"], "OC1-抗丢包")

        yaml_config = yaml.safe_load(yaml.safe_dump(config, sort_keys=False))
        self.assertEqual(yaml_config["obfs"]["type"], "salamander")
        self.assertEqual(
            yaml_config["obfs"]["salamander"]["password"], "adfdafsdfdsfdsf"
        )

    def test_omits_obfs_without_obfs_password(self):
        config = parse_hysteria_url("hysteria2://password@example.com:443")

        self.assertNotIn("obfs", config)


if __name__ == "__main__":
    unittest.main()
