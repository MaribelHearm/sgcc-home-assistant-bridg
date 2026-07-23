import unittest
from unittest.mock import Mock

from sgcc_ha_bridge.captcha_selenium import has_captcha_in_browser


class CaptchaVisibilityTestCase(unittest.TestCase):
    def test_visible_widget_is_detected(self):
        driver = Mock()
        driver.execute_script.return_value = True

        self.assertTrue(has_captcha_in_browser(driver))

    def test_detection_failure_is_treated_as_no_widget(self):
        driver = Mock()
        driver.execute_script.side_effect = RuntimeError("page changed")

        self.assertFalse(has_captcha_in_browser(driver))


if __name__ == "__main__":
    unittest.main()
