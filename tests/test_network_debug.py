import unittest

from sgcc_ha_bridge.network_capture import NetworkRecorder


class FakeDriver:
    current_url = "https://95598.cn/osgweb/login"
    capabilities = {"goog:chromeOptions": {"debuggerAddress": "127.0.0.1:19222"}}


class LoginNetworkMetadataTestCase(unittest.TestCase):
    def test_unscoped_login_response_does_not_read_response_body(self):
        recorder = NetworkRecorder(
            FakeDriver(),
            allowed_hosts={"95598.cn"},
            unscoped_metadata_only=True,
        )
        sent = []
        recorder._send = lambda method, params=None: sent.append((method, params))

        recorder._handle_event("Network.responseReceived", {
            "requestId": "login-request",
            "type": "XHR",
            "response": {
                "url": "https://95598.cn/api/login",
                "status": 200,
                "mimeType": "application/json",
            },
        })
        recorder._handle_event("Network.loadingFinished", {
            "requestId": "login-request",
            "encodedDataLength": 321,
        })

        observations = recorder.observations()
        self.assertEqual(sent, [])
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].source, "network_metadata")
        self.assertEqual(observations[0].scope_id, "login")
        self.assertEqual(observations[0].payload["status"], 200)
        self.assertNotIn("body", observations[0].payload)


if __name__ == "__main__":
    unittest.main()
