import logging
import os
import time
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
import requests

from config import FetcherConfig
from redact import redact_text


def build_driver(config: FetcherConfig):
    chrome_options = webdriver.ChromeOptions()

    browser_lang = os.getenv("BROWSER_LANGUAGE", "zh-HK,zh,en-US,en")
    browser_ua = os.getenv("BROWSER_USER_AGENT", "")
    device_scale = os.getenv("BROWSER_DEVICE_SCALE_FACTOR", "2")
    window_size = os.getenv("BROWSER_WINDOW_SIZE", "1158,848")
    profile_dir = os.getenv("SGCC_BROWSER_PROFILE", "/data/chrome-profile")
    browser_mode = _normalize_browser_mode(os.getenv("SGCC_BROWSER_MODE", "local"))
    browser_service_mode = browser_mode in {
        "browser-service",
        "browser_service",
        "sidecar",
        "container-google-cdp",
        "container_google_cdp",
    }
    cdp_mode = browser_service_mode or browser_mode in {
        "cdp",
        "cdp_attach",
        "host_cdp",
        "host-cdp",
        "remote_debugging",
        "remote-debugging",
    }

    service = _chrome_service(cdp_mode=cdp_mode)

    if cdp_mode:
        cdp_address = _cdp_address_from_env()
        if browser_service_mode:
            _browser_service_start()
            logging.info(f"使用官方 Google Chrome browser-service CDP: {cdp_address}")
        else:
            logging.info(f"使用外部 Google Chrome CDP: {cdp_address}")

        # 连接到已经启动的官方 Google Chrome。这里不再传
        # user-data-dir / binary_location / 启动参数，避免 ChromeDriver
        # 新开容器内 Debian Chromium。
        chrome_options.add_experimental_option("debuggerAddress", cdp_address)
    else:
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument(f"--user-data-dir={profile_dir}")

        # 反检测核心参数（参考 ha-95598）
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        chrome_options.add_argument(f"--lang={browser_lang}")
        chrome_options.add_argument(f"--window-size={window_size}")
        chrome_options.add_argument(f"--force-device-scale-factor={device_scale}")
        chrome_options.add_argument("--high-dpi-support=1")
        if browser_ua:
            chrome_options.add_argument(f"user-agent={browser_ua}")

        chrome_options.add_experimental_option("prefs", {
            "intl.accept_languages": browser_lang,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        })

        if 'PYTHON_IN_DOCKER' in os.environ:
            chrome_options.binary_location = "/usr/bin/chromium"

        logging.info(f"使用 Chromium profile: {profile_dir}")

    def _setting_driver(driver):
        if cdp_mode and os.getenv("SGCC_CDP_SET_WINDOW_SIZE", "").strip().lower() not in {"1", "true", "yes"}:
            return
        width, height = map(int, window_size.split(','))
        try:
            driver.set_window_size(width, height)
        except Exception as e:
            logging.warning(f"设置窗口大小失败: {e}")
        try:
            driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
                "width": width,
                "height": height,
                "deviceScaleFactor": int(device_scale),
                "mobile": False,
                "dontSetVisibleSize": False
            })
        except Exception as e:
            logging.warning(f"CDP 设置 viewport 失败: {e}")

    driver = webdriver.Chrome(options=chrome_options, service=service)
    driver._sgcc_attached_browser = cdp_mode
    driver._sgcc_browser_service_mode = browser_service_mode
    driver.implicitly_wait(config.DRIVER_IMPLICITY_WAIT_TIME)
    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    try:
        driver.set_script_timeout(int(os.getenv("BROWSER_SCRIPT_TIMEOUT", "20")))
    except Exception as e:
        logging.warning(f"设置脚本超时失败: {e}")


    if not cdp_mode:
        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": f"""
                    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
                    Object.defineProperty(navigator, 'languages', {{get: () => {browser_lang.split(',')!r}}});
                    Object.defineProperty(navigator, 'language', {{get: () => '{browser_lang.split(',')[0]}'}});
                """
            })
            try:
                driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {
                    "timezoneId": os.getenv("BROWSER_TIMEZONE", "Asia/Shanghai")
                })
            except Exception as tz_error:
                logging.warning(f"CDP 设置 timezone 失败: {tz_error}")
        except Exception as e:
            logging.warning(f"CDP 注入浏览器一致性脚本失败: {e}")

    _setting_driver(driver)

    return driver


def _normalize_browser_mode(value: str) -> str:
    return (value or "local").strip().lower()


def _cdp_address_from_env() -> str:
    raw_address = os.getenv("SGCC_CDP_ADDRESS", "").strip()
    if raw_address:
        return raw_address

    raw_url = os.getenv("SGCC_CDP_URL", "").strip()
    if raw_url:
        parsed = urlparse(raw_url)
        if parsed.netloc:
            return parsed.netloc
        if parsed.path:
            return parsed.path

    host = os.getenv("SGCC_CDP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("SGCC_CDP_PORT", "9222").strip() or "9222"
    return f"{host}:{port}"


def _browser_service_url() -> str:
    return os.getenv("SGCC_BROWSER_SERVICE_URL", "http://127.0.0.1:39222").strip().rstrip("/")


def _browser_service_start() -> None:
    """Ask the browser-service manager to start official Google Chrome on demand."""
    url = _browser_service_url()
    timeout = float(os.getenv("SGCC_BROWSER_SERVICE_TIMEOUT", "90"))
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            response = requests.post(f"{url}/start", timeout=10)
            if response.status_code < 400:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except Exception as e:
            last_error = e
        time.sleep(1)
    raise RuntimeError(f"启动 SGCC Chrome browser-service 失败: {redact_text(last_error)}")


def _browser_service_stop() -> None:
    url = _browser_service_url()
    try:
        response = requests.post(f"{url}/stop", timeout=10)
        if response.status_code >= 400:
            logging.warning(f"停止 SGCC Chrome browser-service 失败: HTTP {response.status_code}: {redact_text(response.text[:300])}")
    except Exception as e:
        logging.warning(f"停止 SGCC Chrome browser-service 异常: {redact_text(e)}")


def _chrome_service(cdp_mode: bool = False) -> ChromeService:
    configured = os.getenv("SGCC_CHROMEDRIVER_PATH", "").strip()
    if configured:
        return ChromeService(executable_path=configured)

    if 'PYTHON_IN_DOCKER' in os.environ:
        # local mode drives Debian Chromium, so keep Debian chromedriver first.
        # browser-service/CDP mode attaches to official Google Chrome; prefer the
        # Chrome-for-Testing driver installed beside google-chrome-stable.
        candidates = (
            ["/usr/local/bin/chromedriver", "/usr/bin/chromedriver"]
            if cdp_mode
            else ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver"]
        )
        for path in candidates:
            if os.path.exists(path):
                return ChromeService(executable_path=path)
        return ChromeService(executable_path="/usr/bin/chromedriver")
    return _find_chromedriver()


def _find_chromedriver() -> ChromeService:
    """在非 Docker 环境中查找可用的 ChromeDriver。"""
    import shutil

    # 1) 尝试系统 PATH
    path = shutil.which("chromedriver") or shutil.which("chromedriver.exe")
    if path:
        return ChromeService(executable_path=path)

    # 2) 尝试 CloakBrowser 缓存的 chromedriver（如果有）
    for base in [
        os.path.expanduser("~/.cloakbrowser"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), ".cloakbrowser"),
    ]:
        try:
            for root, dirs, files in os.walk(base):
                if "chromedriver.exe" in files or "chromedriver" in files:
                    fname = "chromedriver.exe" if "chromedriver.exe" in files else "chromedriver"
                    path = os.path.join(root, fname)
                    if os.path.isfile(path):
                        return ChromeService(executable_path=path)
                # 最多扫描两级目录
                if len(root) - len(base) > 200:
                    dirs.clear()
        except Exception:
            pass

    # 3) 尝试 Selenium Manager 自动下载
    try:
        return ChromeService()
    except Exception:
        pass

    raise RuntimeError(
        "ChromeDriver 未找到。请安装 ChromeDriver 或运行: pip install chromedriver-binary-auto"
    )


def release_driver(driver) -> None:
    attached_browser = bool(getattr(driver, "_sgcc_attached_browser", False))
    browser_service_mode = bool(getattr(driver, "_sgcc_browser_service_mode", False))
    try:
        if attached_browser:
            try:
                driver.command_executor.close()
            except Exception:
                pass
            try:
                driver.service.stop()
            except Exception:
                pass
            if browser_service_mode and os.getenv("SGCC_BROWSER_SERVICE_STOP_ON_RELEASE", "true").strip().lower() not in {"0", "false", "no"}:
                _browser_service_stop()
                logging.info("浏览器驱动已断开；browser-service Chrome 已按需关闭。")
            else:
                logging.info("浏览器驱动已断开；外部 Chrome 保持原运行状态。")
            return
        driver.quit()
        logging.info("数据抓取完成后浏览器驱动退出。")
    except Exception as e:
        logging.warning(f"浏览器驱动退出失败: {redact_text(e)}")
