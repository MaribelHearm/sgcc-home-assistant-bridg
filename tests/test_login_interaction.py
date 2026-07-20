import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sgcc_ha_bridge.login_interaction import (
    NoopLoginInteraction,
    TelegramLoginInteraction,
    build_login_interaction,
    read_sms_code,
)


def response(result, status_code=200):
    return SimpleNamespace(
        status_code=status_code,
        json=lambda: {"ok": status_code == 200, "result": result},
    )


class TelegramLoginInteractionTestCase(unittest.TestCase):
    def test_builds_from_primary_environment_names(self):
        with patch.dict(os.environ, {
            "SGCC_LOGIN_INTERACTION_PROVIDER": "telegram",
            "SGCC_TELEGRAM_BOT_TOKEN": "123456:secret",
            "SGCC_TELEGRAM_CHAT_ID": "42",
            "SGCC_TELEGRAM_API_BASE_URL": "telegram.local/",
        }, clear=True):
            interaction = build_login_interaction()

        self.assertIsInstance(interaction, TelegramLoginInteraction)
        self.assertEqual(interaction.bot_url, "https://telegram.local/bot123456:secret")

    def test_rejects_insecure_or_credentialed_api_base_urls(self):
        for api_base_url in (
            "http://telegram.local",
            "https://user:pass@telegram.local",
            "https://telegram.local?token=leak",
            "https://telegram.local#fragment",
        ):
            with self.subTest(api_base_url=api_base_url), patch.dict(os.environ, {
                "SGCC_LOGIN_INTERACTION_PROVIDER": "telegram",
                "SGCC_TELEGRAM_BOT_TOKEN": "123456:secret",
                "SGCC_TELEGRAM_CHAT_ID": "42",
                "SGCC_TELEGRAM_API_BASE_URL": api_base_url,
            }, clear=True):
                interaction = build_login_interaction()

            self.assertIsInstance(interaction, NoopLoginInteraction)

    def test_missing_telegram_credentials_falls_back_to_noop(self):
        with patch.dict(os.environ, {
            "SGCC_LOGIN_INTERACTION_PROVIDER": "telegram",
        }, clear=True):
            interaction = build_login_interaction()

        self.assertIsInstance(interaction, NoopLoginInteraction)

    @patch("sgcc_ha_bridge.login_interaction.requests.post")
    def test_qrcode_is_sent_to_configured_chat(self, post):
        post.return_value = response({"message_id": 7})
        interaction = TelegramLoginInteraction("token", "42")

        self.assertTrue(interaction.send_qr_code(b"png", "RK001"))

        url, = post.call_args.args
        kwargs = post.call_args.kwargs
        self.assertEqual(url, "https://api.telegram.org/bottoken/sendPhoto")
        self.assertEqual(kwargs["data"]["chat_id"], "42")
        self.assertIn("photo", kwargs["files"])
        self.assertNotIn("token", str(kwargs))

    @patch("sgcc_ha_bridge.login_interaction.time.monotonic")
    @patch("sgcc_ha_bridge.login_interaction.requests.post")
    def test_sms_accepts_only_reply_to_current_prompt_from_allowed_chat(self, post, monotonic):
        monotonic.side_effect = [0, 0, 1]
        post.side_effect = [
            response([{"update_id": 10}]),
            response({"message_id": 99}),
            response([
                {
                    "update_id": 11,
                    "message": {
                        "chat": {"id": 999},
                        "reply_to_message": {"message_id": 99},
                        "text": "123456",
                    },
                },
                {
                    "update_id": 12,
                    "message": {
                        "chat": {"id": 42},
                        "reply_to_message": {"message_id": 98},
                        "text": "654321",
                    },
                },
                {
                    "update_id": 13,
                    "message": {
                        "chat": {"id": 42},
                        "reply_to_message": {"message_id": 99},
                        "text": "246810",
                    },
                },
            ]),
        ]
        interaction = TelegramLoginInteraction("token", "42", sms_wait_seconds=60)

        self.assertEqual(interaction.request_sms_code("RK001"), "246810")

        poll_kwargs = post.call_args_list[2].kwargs["json"]
        self.assertEqual(poll_kwargs["offset"], 11)

    @patch("sgcc_ha_bridge.login_interaction.time.monotonic")
    @patch("sgcc_ha_bridge.login_interaction.requests.post")
    def test_invalid_sms_reply_is_not_returned(self, post, monotonic):
        monotonic.side_effect = [0, 0, 1, 61]
        post.side_effect = [
            response([]),
            response({"message_id": 99}),
            response([{
                "update_id": 1,
                "message": {
                    "chat": {"id": 42},
                    "reply_to_message": {"message_id": 99},
                    "text": "code=123456",
                },
            }]),
            response({"message_id": 100}),
            response({"message_id": 101}),
        ]
        interaction = TelegramLoginInteraction("token", "42", sms_wait_seconds=60)

        self.assertIsNone(interaction.request_sms_code("test"))

    @patch("sgcc_ha_bridge.login_interaction.requests.post")
    def test_http_failure_does_not_log_bot_response_body(self, post):
        post.return_value = response(None, status_code=500)
        interaction = TelegramLoginInteraction("sensitive-token", "42")

        with self.assertLogs(level="WARNING") as logs:
            self.assertFalse(interaction.send_qr_code(b"png", "test"))

        self.assertNotIn("sensitive-token", "\n".join(logs.output))

    def test_non_interactive_sms_without_provider_returns_none(self):
        interaction = NoopLoginInteraction()
        with patch("sgcc_ha_bridge.login_interaction.sys.stdin", None):
            self.assertIsNone(read_sms_code(interaction, "test"))

    @patch("sgcc_ha_bridge.login_interaction.requests.post")
    def test_get_updates_conflict_stops_before_sending_sms_prompt(self, post):
        post.return_value = response(None, status_code=409)
        interaction = TelegramLoginInteraction("sensitive-token", "42")

        with self.assertLogs(level="WARNING"):
            self.assertIsNone(interaction.request_sms_code("test"))

        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args.args[0].endswith("/getUpdates"))

    @patch("sgcc_ha_bridge.login_interaction.time.monotonic")
    @patch("sgcc_ha_bridge.login_interaction.requests.post")
    def test_next_request_reuses_consumed_update_offset(self, post, monotonic):
        monotonic.side_effect = [0, 0, 1, 0, 0, 1]
        post.side_effect = [
            response([{"update_id": 10}]),
            response({"message_id": 99}),
            response([{
                "update_id": 11,
                "message": {
                    "chat": {"id": 42},
                    "reply_to_message": {"message_id": 99},
                    "text": "123456",
                },
            }]),
            response({"message_id": 100}),
            response([{
                "update_id": 12,
                "message": {
                    "chat": {"id": 42},
                    "reply_to_message": {"message_id": 100},
                    "text": "654321",
                },
            }]),
        ]
        interaction = TelegramLoginInteraction("token", "42", sms_wait_seconds=60)

        self.assertEqual(interaction.request_sms_code("first"), "123456")
        self.assertEqual(interaction.request_sms_code("second"), "654321")

        self.assertEqual(post.call_count, 5)
        self.assertEqual(post.call_args_list[4].kwargs["json"]["offset"], 12)


if __name__ == "__main__":
    unittest.main()
