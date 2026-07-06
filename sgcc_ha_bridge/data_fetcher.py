import logging
import os
import random
import threading
import time

from .browser import build_driver, release_driver
from .cache_validity import has_useful_account_data
from .config import FetcherConfig
from .const import LOGIN_URL
from .error_watcher import ErrorWatcher
from .ha_mapping import account_data_summary, account_data_to_update_args, with_history_daily_if_empty
from .login import SgccLogin
from .login_guard import (
    LoginFailure,
    NonRetryableFetchError,
    clear_login_cooldown,
    env_bool,
    get_login_cooldown,
    set_login_cooldown,
    should_retry_login_failure,
)
from .mqtt_publisher import MqttPublisher
from .model import FetchRun, mask_account_no
from .redact import install_account_log_redaction, mask_secret, now_iso, redact_text
from .scraper import Scraper, redact_account_data
from .sensor_updator import SensorUpdator
from .session import check_session
from .store import Store

_FETCH_LOCK = threading.Lock()


class DataFetcher:

    def __init__(self, username: str, password: str):
        self.config = FetcherConfig.from_env()
        self._username = username
        self._password = password

    @staticmethod
    def _mask_secret(value: str, keep_last: int = 2) -> str:
        return mask_secret(value, keep_last=keep_last)

    @staticmethod
    def _redact_text(value) -> str:
        return redact_text(value)

    def _random_delay(self, min_seconds=0.5, max_seconds=3.0):
        """添加随机延迟，使自动化操作更难被检测。"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    def fetch(self, trigger_type: str = "manual"):

        """主逻辑：登录链路保持原样，数据抓取切换到 Path B + Store。"""

        install_account_log_redaction()

        if not _FETCH_LOCK.acquire(blocking=False):
            self._record_skipped_busy_run(trigger_type)
            logging.info("已有抓取任务正在运行，本次 fetch 标记为 skipped_busy 后跳过。")
            return "skipped_busy"

        driver = None
        store = None
        run_id = None
        session_status_before = "unknown"
        session_status_after = "unknown"
        try:
            store = Store()
            run_id = store.start_run(FetchRun(
                trigger_type=trigger_type,
                started_at=now_iso(),
            ))

            if env_bool("SGCC_LOGIN_COOLDOWN_ENABLED", True) and trigger_type != "manual":
                cooldown = get_login_cooldown()
                if cooldown.active:
                    message = (
                        f"登录风控冷却中，剩余 {cooldown.remaining_seconds // 60} 分钟，"
                        f"跳过本次无人值守登录: {cooldown.reason}"
                    )
                    logging.warning(message)
                    store.finish_run(
                        run_id,
                        "skipped_cooldown",
                        session_status_before=session_status_before,
                        session_status_after=session_status_after,
                        error_type="LoginCooldown",
                        error_message_redacted=redact_text(message),
                    )
                    return "skipped_cooldown"

            driver = build_driver(self.config)
            ErrorWatcher.instance().set_driver(driver)

            self._random_delay(1, 3)
            logging.info("浏览器驱动已初始化。")
            publisher = self.config.PUBLISHER
            if publisher not in {"rest", "mqtt", "both"}:
                logging.warning(f"未知 PUBLISHER={publisher}，回退为 mqtt。")
                publisher = "mqtt"
            updator = SensorUpdator() if publisher in {"rest", "both"} else None
            mqtt_pub = MqttPublisher(self.config) if publisher in {"mqtt", "both"} else None
            mqtt_connected = mqtt_pub.connect() if mqtt_pub is not None else False

            before_check = check_session(driver, "before_login")
            session_status_before = before_check.status
            store.record_session_check(before_check)

            try:
                login_client = SgccLogin(driver, self._username, self._password, self.config)
                if os.getenv("DEBUG_MODE", "false").lower() == "true":
                    logged_in = login_client.login(phone_code=True)
                else:
                    allow_fallback = env_bool("SGCC_QRCODE_FALLBACK_UNATTENDED", False) or trigger_type == "manual"
                    logged_in = login_client.login(allow_fallback=allow_fallback)
                if logged_in:
                    logging.info("登录成功!")
                else:
                    logging.info("登录失败!")
                    raise LoginFailure("login_failed", "login unsuccessed")
            except LoginFailure as e:
                if not should_retry_login_failure(e.category):
                    cooldown = set_login_cooldown(f"{e.category}: {e.message}")
                    logging.error(
                        f"登录失败[{e.category}]，判定为不应立即重试；已熔断到 "
                        f"{cooldown.until.isoformat() if cooldown.until else 'unknown'}: {redact_text(e.message)}"
                    )
                    raise NonRetryableFetchError(str(e)) from e
                logging.error(
                    f"登录失败[{e.category}]，原因: {redact_text(e.message)}。"
                    f"还剩 {self.config.RETRY_TIMES_LIMIT} 次重试机会。"
                )
                raise
            except Exception as e:
                logging.error(
                    f"浏览器驱动异常，原因: {redact_text(e)}。还剩 {self.config.RETRY_TIMES_LIMIT} 次重试机会。")
                raise

            logging.info(f"在 {LOGIN_URL} 登录成功")
            after_login_check = check_session(driver, "after_login")
            store.record_session_check(after_login_check)
            session_status_after = after_login_check.status

            if after_login_check.status != "authenticated":
                raise Exception(f"session not authenticated after login: {after_login_check.status}")

            self._random_delay(1, 3)
            logging.info("开始使用 Path B 从 Vue/Vuex 状态抓取账户数据。")
            account_data_list = Scraper(driver).fetch_all()
            if not account_data_list:
                raise Exception("Path B 未抓取到任何账户数据")

            saved_count = 0
            for account_data in account_data_list:
                user_id = account_data.account.account_no
                masked_user_id = mask_account_no(user_id)
                if not user_id:
                    logging.warning("Path B 返回了缺少户号的账户数据，已跳过。")
                    continue
                if user_id in self.config.IGNORE_USER_ID:
                    logging.info(f"用户 ID {masked_user_id} 将被忽略")
                    continue

                if not has_useful_account_data(account_data):
                    logging.warning(
                        f"用户 [{masked_user_id}] Path B 只返回户号/元数据，没有任何有效国网业务数据，已跳过。"
                    )
                    continue

                store.save_account_data(account_data, run_id)
                saved_count += 1
                logging.info(f"用户 [{masked_user_id}] Path B 数据已写入 Store: {account_data_summary(account_data)}")
                logging.debug(f"用户 [{masked_user_id}] Path B 脱敏数据: {redact_account_data(account_data)}")

                publish_account_data = with_history_daily_if_empty(account_data, store, limit=31)
                if publish_account_data is not account_data:
                    logging.info(
                        f"用户 [{masked_user_id}] 本次抓取 daily 为空，发布前从 Store 回填 "
                        f"{len(publish_account_data.daily)} 条历史日用电数据。"
                    )

                update_args = account_data_to_update_args(publish_account_data)
                cache_args = account_data_to_update_args(account_data)
                logging.info(
                    f"用户 [{masked_user_id}] 数据获取完成: 余额={update_args['balance']}元, "
                    f"预付费余额={update_args['prepay_balance']}元, "
                    f"应交金额={update_args['arrears']}元, "
                    f"最近日用电={update_args['last_daily_usage']}度({update_args['last_daily_date']}), "
                    f"年度用电={update_args['yearly_usage']}度, 年度电费={update_args['yearly_charge']}元, "
                    f"月用电={update_args['month_usage']}度, 月电费={update_args['month_charge']}元")
                if updator is not None:
                    if updator.update_one_userid(**update_args, cache_values=cache_args) is False:
                        logging.warning(
                            f"用户 [{masked_user_id}] Home Assistant REST 发布未完全成功；国网抓取和本地 Store 已完成，不触发重新登录。"
                        )
                if mqtt_pub is not None:
                    try:
                        if not mqtt_connected:
                            logging.warning(f"用户 [{masked_user_id}] MQTT 未连接，跳过发布。")
                        elif not mqtt_pub.publish_account_data(publish_account_data):
                            logging.warning(f"用户 [{masked_user_id}] MQTT 发布失败，已跳过。")
                    except Exception as mqtt_error:
                        logging.warning(f"用户 [{masked_user_id}] MQTT 发布异常，已忽略: {redact_text(mqtt_error)}")

            if saved_count == 0:
                raise Exception("Path B 抓取结果均为空或被忽略，未写入任何账户数据")

            final_check = check_session(driver, "after_fetch")
            store.record_session_check(final_check)
            session_status_after = final_check.status
            store.finish_run(
                run_id,
                "success",
                session_status_before=session_status_before,
                session_status_after=session_status_after,
            )
            logging.info(f"抓取运行 {run_id} 完成: success, 账户数={saved_count}, 会话={session_status_after}")
            clear_login_cooldown()
            return "success"
        except Exception as e:
            if driver is not None and store is not None:
                try:
                    failed_check = check_session(driver, "failed")
                    store.record_session_check(failed_check)
                    session_status_after = failed_check.status
                except Exception:
                    pass
            if store is not None and run_id is not None:
                try:
                    store.finish_run(
                        run_id,
                        "failed",
                        session_status_before=session_status_before,
                        session_status_after=session_status_after,
                        error_type=type(e).__name__,
                        error_message_redacted=redact_text(e),
                    )
                except Exception as finish_error:
                    logging.warning(f"记录 fetch run 失败状态失败: {redact_text(finish_error)}")
            raise
        finally:
            if driver is not None:
                release_driver(driver)
            if "mqtt_pub" in locals() and mqtt_pub is not None:
                mqtt_pub.disconnect()
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
            _FETCH_LOCK.release()

    def _record_skipped_busy_run(self, trigger_type: str) -> None:
        try:
            with Store() as store:
                now = now_iso()
                store.start_run(FetchRun(
                    trigger_type=trigger_type,
                    status="skipped_busy",
                    started_at=now,
                    finished_at=now,
                    session_status_before="unknown",
                    session_status_after="unknown",
                ))
        except Exception as e:
            logging.warning(f"记录 skipped_busy fetch run 失败: {redact_text(e)}")
