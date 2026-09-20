import unittest
from unittest.mock import patch

from utils import method


class BmspointMappingTest(unittest.TestCase):
    def test_read_param_value_returns_mapped_string(self):
        param = {
            "name": "bms.bank.systemRunMode",
            "address": 38071,
            "offset": 1,
            "precision": "1",
            "unit": "",
            "valueType": "uint16",
            "pointMapping": {
                0: "status.standby",
                1: "status.running",
            },
        }

        with patch.object(method, "query_register_data", return_value=[1]):
            self.assertEqual(method._read_param_value(param), "status.running")


if __name__ == "__main__":
    unittest.main()
