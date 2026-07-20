import logging
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from selenium.common.exceptions import TimeoutException

from sgcc_ha_bridge.error_watcher import ErrorWatcher
from sgcc_ha_bridge.login import SgccLogin
from sgcc_ha_bridge.login_guard import LoginFailure


class LoginFallbackTestCase(unittest.TestCase):
    def test_fallback_method_aliases_are_normalized_and_ordered(self):
        with patch.dict(os.environ, {
            "SGCC_LOGIN_FALLBACK_METHODS": "sms,qrcode,phone_code,qrcode",
        }, clear=True):
            self.assertEqual(SgccLogin._fallback_methods(), ["phone-code", "qrcode"])

    def test_fallback_tries_next_method_after_sms_failure(self):
        login = SgccLogin.__new__(SgccLogin)
        login._phone_code_login = Mock(side_effect=LoginFailure("phone_code_timeout", "timeout"))
        login._qr_login = Mock(return_value=True)

        with self.assertLogs(level=logging.WARNING) as logs:
            result = login._fallback_login(object(), "RK001", ["phone-code", "qrcode"])

        self.assertTrue(result)
        login._phone_code_login.assert_called_once()
        login._qr_login.assert_called_once()
        self.assertIn("phone-code", "\n".join(logs.output))

    def test_fallback_stops_when_sms_hits_risk_block(self):
        login = SgccLogin.__new__(SgccLogin)
        login._phone_code_login = Mock(
            side_effect=LoginFailure("risk_blocked", "网络连接超时（RK001）")
        )
        login._qr_login = Mock(return_value=True)

        with patch.dict(os.environ, {}, clear=True), self.assertLogs(
            level=logging.WARNING
        ), self.assertRaises(LoginFailure) as raised:
            login._fallback_login(object(), "password failed", ["phone-code", "qrcode"])

        self.assertEqual(raised.exception.category, "risk_blocked")
        login._qr_login.assert_not_called()

    def test_risk_override_allows_next_fallback_after_sms_risk_block(self):
        login = SgccLogin.__new__(SgccLogin)
        login._phone_code_login = Mock(
            side_effect=LoginFailure("risk_blocked", "网络连接超时（RK001）")
        )
        login._qr_login = Mock(return_value=True)

        with patch.dict(
            os.environ, {"SGCC_RISK_FALLBACK_OVERRIDE": "true"}, clear=True
        ), self.assertLogs(level=logging.WARNING):
            result = login._fallback_login(
                object(), "password failed", ["phone-code", "qrcode"]
            )

        self.assertTrue(result)
        login._qr_login.assert_called_once()

    def test_error_route_without_token_or_authenticated_dom_is_not_logged_in(self):
        driver = Mock()
        driver.current_url = "https://95598.cn/osgweb/callback-error"
        driver.execute_script.side_effect = [False, False]

        self.assertFalse(SgccLogin.is_logged_in_page(driver))

    @patch("sgcc_ha_bridge.login.build_login_interaction")
    @patch("sgcc_ha_bridge.login.read_sms_code")
    def test_phone_code_requires_confirmed_authenticated_state(self, read_code, build_interaction):
        driver = Mock()
        driver.find_elements.return_value = [Mock(), Mock(), Mock(), Mock()]
        login = SgccLogin.__new__(SgccLogin)
        login.driver = driver
        login._username = "13800000000"
        login.config = SimpleNamespace(RETRY_WAIT_TIME_OFFSET_UNIT=0)
        login._click_button = Mock()
        login._get_error_message = Mock(return_value="验证码错误")
        interaction = Mock()
        build_interaction.return_value = interaction
        read_code.return_value = "123456"

        with patch.object(SgccLogin, "is_logged_in_page", return_value=False):
            with self.assertRaises(LoginFailure):
                login._phone_code_login(driver, "RK001")

        interaction.notify_result.assert_called_once_with(
            "phone-code",
            False,
            "验证码提交后仍未检测到登录态",
        )
        self.assertNotIn("123456", str(interaction.mock_calls))

    @patch("sgcc_ha_bridge.login.build_login_interaction")
    @patch("sgcc_ha_bridge.login.WebDriverWait")
    def test_qrcode_requires_confirmed_authenticated_state(self, wait, build_interaction):
        driver = Mock()
        driver.current_url = "https://95598.cn/osgweb/callback-error"
        qr_element = Mock()
        qr_element.get_attribute.return_value = "data:image/png;base64,cG5n"
        wait.return_value.until.side_effect = [Mock(), qr_element, TimeoutException()]

        login = SgccLogin.__new__(SgccLogin)
        login.driver = driver
        login.config = SimpleNamespace(
            DRIVER_IMPLICITY_WAIT_TIME=1,
            RETRY_WAIT_TIME_OFFSET_UNIT=0,
            QR_CODE_LOGIN_WAIT_COUNT=1,
            QR_CODE_LOGIN_WAIT_TIME_INTERVAL_UNIT=0,
        )
        interaction = Mock()
        build_interaction.return_value = interaction

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "sgcc_ha_bridge.login.get_data_dir", return_value=tmpdir
        ), patch.object(
            SgccLogin, "is_logged_in_page", return_value=False
        ), patch("sgcc_ha_bridge.login.time.sleep"):
            self.assertFalse(login._qr_login(driver, "test"))

        interaction.notify_result.assert_called_once_with(
            "qrcode",
            False,
            "扫码后仍未确认登录态",
        )

    def test_risk_blocked_skips_interactive_fallback(self):
        login = SgccLogin.__new__(SgccLogin)
        login.driver = Mock()
        login._username = "13800000000"
        login._password = "password"
        login.config = SimpleNamespace(
            DRIVER_IMPLICITY_WAIT_TIME=0,
            RETRY_WAIT_TIME_OFFSET_UNIT=0,
            RETRY_TIMES_LIMIT=1,
        )
        login._safe_get = Mock()
        login._click_button = Mock()
        login._get_error_message = Mock(return_value="网络连接超时（RK001）,请重试！")
        login._fallback_login = Mock(return_value=True)
        login.driver.find_elements.return_value = [Mock(), Mock()]
        login.driver.current_url = "https://95598.cn/osgweb/login"

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ, {}, clear=True
        ), patch.object(
            ErrorWatcher, "_instance", ErrorWatcher(root_dir=tmpdir, driver=login.driver)
        ), patch.object(SgccLogin, "is_logged_in_page", return_value=False), patch(
            "sgcc_ha_bridge.login.WebDriverWait"
        ) as wait, patch("sgcc_ha_bridge.login.time.sleep"):
            wait.return_value.until.return_value = Mock()
            with self.assertRaises(LoginFailure) as raised:
                login.login(allow_fallback=True, fallback_methods=["phone-code"])

        self.assertEqual(raised.exception.category, "risk_blocked")
        login._fallback_login.assert_not_called()

    @patch("sgcc_ha_bridge.login.solve_captcha_in_browser", return_value=True)
    def test_risk_override_allows_fallback_after_captcha_passes(self, solve_captcha):
        login = SgccLogin.__new__(SgccLogin)
        login.driver = Mock()
        login._username = "13800000000"
        login._password = "password"
        login.config = SimpleNamespace(
            DRIVER_IMPLICITY_WAIT_TIME=0,
            RETRY_WAIT_TIME_OFFSET_UNIT=0,
            RETRY_TIMES_LIMIT=1,
        )
        login._safe_get = Mock()
        login._click_button = Mock()
        login._get_error_message = Mock(
            side_effect=[None, "网络连接超时（RK001）,请重试！"]
        )
        login._fallback_login = Mock(return_value=True)
        login.driver.find_elements.return_value = [Mock(), Mock()]
        login.driver.current_url = "https://95598.cn/osgweb/login"

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ, {"SGCC_RISK_FALLBACK_OVERRIDE": "true"}, clear=True
        ), patch.object(
            ErrorWatcher, "_instance", ErrorWatcher(root_dir=tmpdir, driver=login.driver)
        ), patch.object(SgccLogin, "is_logged_in_page", return_value=False), patch(
            "sgcc_ha_bridge.login.WebDriverWait"
        ) as wait, patch("sgcc_ha_bridge.login.time.sleep"):
            wait.return_value.until.return_value = Mock()
            self.assertTrue(
                login.login(allow_fallback=True, fallback_methods=["phone-code"])
            )

        solve_captcha.assert_called_once()
        login._fallback_login.assert_called_once_with(
            login.driver,
            "网络连接超时（RK001）,请重试！",
            ["phone-code"],
        )

    @patch("sgcc_ha_bridge.login.solve_captcha_in_browser", return_value=True)
    def test_failed_risk_override_fallback_preserves_risk_category(self, solve_captcha):
        login = SgccLogin.__new__(SgccLogin)
        login.driver = Mock()
        login._username = "13800000000"
        login._password = "password"
        login.config = SimpleNamespace(
            DRIVER_IMPLICITY_WAIT_TIME=0,
            RETRY_WAIT_TIME_OFFSET_UNIT=0,
            RETRY_TIMES_LIMIT=1,
        )
        login._safe_get = Mock()
        login._click_button = Mock()
        login._get_error_message = Mock(
            side_effect=[None, "网络连接超时（RK001）,请重试！"]
        )
        login._fallback_login = Mock(return_value=False)
        login.driver.find_elements.return_value = [Mock(), Mock()]
        login.driver.current_url = "https://95598.cn/osgweb/login"

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ, {"SGCC_RISK_FALLBACK_OVERRIDE": "true"}, clear=True
        ), patch.object(
            ErrorWatcher, "_instance", ErrorWatcher(root_dir=tmpdir, driver=login.driver)
        ), patch.object(SgccLogin, "is_logged_in_page", return_value=False), patch(
            "sgcc_ha_bridge.login.WebDriverWait"
        ) as wait, patch("sgcc_ha_bridge.login.time.sleep"):
            wait.return_value.until.return_value = Mock()
            with self.assertRaises(LoginFailure) as raised:
                login.login(allow_fallback=True, fallback_methods=["phone-code"])

        self.assertEqual(raised.exception.category, "risk_blocked")
        solve_captcha.assert_called_once()
        login._fallback_login.assert_called_once()


if __name__ == "__main__":
    unittest.main()
