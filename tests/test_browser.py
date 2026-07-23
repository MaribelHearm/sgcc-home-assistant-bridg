import os
import unittest
from unittest.mock import Mock, patch

from sgcc_ha_bridge.browser import (
    _apply_browser_consistency,
    _log_browser_runtime,
    release_driver,
)


class BrowserConsistencyTestCase(unittest.TestCase):
    def test_consistency_is_applied_before_navigation_for_attached_driver(self):
        driver = Mock()

        _apply_browser_consistency(driver, "zh-CN,zh,en-US,en")

        commands = [call.args[0] for call in driver.execute_cdp_cmd.call_args_list]
        self.assertEqual(
            commands,
            [
                "Page.addScriptToEvaluateOnNewDocument",
                "Emulation.setTimezoneOverride",
                "Emulation.setLocaleOverride",
            ],
        )
        script = driver.execute_cdp_cmd.call_args_list[0].args[1]["source"]
        self.assertIn("Navigator.prototype", script)
        self.assertIn("'webdriver'", script)
        self.assertIn('"zh-CN"', script)
        driver.execute_script.assert_called_once_with(script)

    def test_runtime_snapshot_only_runs_in_debug_mode(self):
        driver = Mock()

        with patch.dict(os.environ, {}, clear=True):
            _log_browser_runtime(driver)

        driver.execute_script.assert_not_called()

    @patch("sgcc_ha_bridge.browser._browser_service_stop")
    def test_browser_service_closes_chrome_on_release_by_default(self, stop):
        driver = Mock()
        driver._sgcc_attached_browser = True
        driver._sgcc_browser_service_mode = True

        with patch.dict(os.environ, {}, clear=True):
            release_driver(driver)

        stop.assert_called_once_with()
        driver.command_executor.close.assert_called_once_with()
        driver.service.stop.assert_called_once_with()
        driver.quit.assert_not_called()

    @patch("sgcc_ha_bridge.browser._browser_service_stop")
    def test_browser_service_can_explicitly_keep_chrome_running(self, stop):
        driver = Mock()
        driver._sgcc_attached_browser = True
        driver._sgcc_browser_service_mode = True

        with patch.dict(
            os.environ,
            {"SGCC_BROWSER_SERVICE_STOP_ON_RELEASE": "false"},
            clear=True,
        ):
            release_driver(driver)

        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
