import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from institutional_options.fyers_client import FyersAPIError, FyersCredentials, FyersRestClient, TokenStore


class FyersTransientAuthTests(unittest.TestCase):
    def test_rate_limit_does_not_clear_saved_token_or_prompt_login(self):
        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "tokens.json"
            token_path.write_text(json.dumps({"access_token": "saved", "refresh_token": ""}), encoding="utf-8")
            client = FyersRestClient(FyersCredentials("APP-100", "secret"), TokenStore(token_path))
            for error in (
                FyersAPIError("rate limited", status_code=429),
                FyersAPIError("cloudflare Error 1010 access denied", status_code=403),
            ):
                with patch.object(client, "_probe", side_effect=error):
                    header = client.ensure_session(interactive=False)
                self.assertEqual(header, "APP-100:saved")
                self.assertTrue(token_path.exists())
                self.assertEqual(json.loads(token_path.read_text(encoding="utf-8"))["access_token"], "saved")


if __name__ == "__main__":
    unittest.main()
