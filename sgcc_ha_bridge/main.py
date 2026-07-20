import logging
import logging.config
import os
import sys
import time
import schedule
import json
import random
from .error_watcher import ErrorWatcher
from .sensor_updator import SensorUpdator
from datetime import date, datetime, timedelta
from typing import Callable
from .const import *
from .config import FetcherConfig
from .cache_validity import (
    account_data_has_recent_cache_value,
    has_useful_account_data,
    has_useful_legacy_cache_entry,
)
from .data_fetcher import DataFetcher
from .model import Account, AccountData, Balance, DailyReading, MonthlyReading, YearlyReading, mask_account_no
from .mqtt_publisher import MqttPublisher
from .redact import redact_text
from .store import Store
from .login_guard import NonRetryableFetchError, env_bool, get_login_cooldown


DEFAULT_DAILY_JITTER_MINUTES = 10
MAX_DAILY_JITTER_MINUTES = 180


def _daily_jitter_minutes(raw_value=None) -> int:
    raw_value = os.getenv("SGCC_DAILY_JITTER_MINUTES") if raw_value is None else raw_value
    if raw_value is None:
        return DEFAULT_DAILY_JITTER_MINUTES
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        logging.warning(
            f"SGCC_DAILY_JITTER_MINUTES={raw_value!r} 无效，已回退为默认 "
            f"{DEFAULT_DAILY_JITTER_MINUTES} 分钟。"
        )
        return DEFAULT_DAILY_JITTER_MINUTES
    if not 0 <= value <= MAX_DAILY_JITTER_MINUTES:
        logging.warning(
            f"SGCC_DAILY_JITTER_MINUTES={value} 超出 0..{MAX_DAILY_JITTER_MINUTES}，"
            f"已回退为默认 {DEFAULT_DAILY_JITTER_MINUTES} 分钟。"
        )
        return DEFAULT_DAILY_JITTER_MINUTES
    return value


def _daily_schedule_times(job_start_time: str, jitter_minutes: int, daily_runs: int = 1, randint=random.randint):
    offset_minutes = randint(-jitter_minutes, jitter_minutes) if jitter_minutes else 0
    first_run = datetime.strptime(job_start_time, "%H:%M") + timedelta(minutes=offset_minutes)
    run_times = [first_run.strftime("%H:%M")]
    if daily_runs >= 2:
        run_times.append((first_run + timedelta(hours=12)).strftime("%H:%M"))
    return offset_minutes, run_times


class DailyJitterScheduler:
    """Schedule one logical day's runs, then draw a new offset for the next day."""

    def __init__(
        self,
        scheduler,
        job_start_time: str,
        jitter_minutes: int,
        daily_runs: int,
        job_func: Callable,
        *job_args,
        randint=random.randint,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.scheduler = scheduler
        self.job_start_time = job_start_time
        self.jitter_minutes = jitter_minutes
        self.daily_runs = daily_runs
        self.job_func = job_func
        self.job_args = job_args
        self.randint = randint
        self.now = now
        self._scheduled_for: date | None = None
        self._jobs = []

    def schedule_day(self, target_date: date | None = None) -> list[datetime]:
        target_date = target_date or self.now().date()
        current_time = self.now()
        while True:
            offset_minutes, run_times = _daily_schedule_times(
                self.job_start_time,
                self.jitter_minutes,
                self.daily_runs,
                randint=self.randint,
            )
            first_time = datetime.strptime(self.job_start_time, "%H:%M").time()
            first_run = datetime.combine(target_date, first_time) + timedelta(minutes=offset_minutes)
            run_datetimes = [first_run]
            if self.daily_runs >= 2:
                run_datetimes.append(first_run + timedelta(hours=12))
            future_runs = [
                (run_index, run_at)
                for run_index, run_at in enumerate(run_datetimes, start=1)
                if run_at > current_time
            ]
            if future_runs:
                break
            target_date += timedelta(days=1)

        self.clear()
        for position, (run_index, run_at) in enumerate(future_runs):
            job = self.scheduler.every().day.at(run_at.strftime("%H:%M")).do(
                safe_scheduled_job,
                self._run_once,
                target_date,
                run_index,
                run_at,
                position == len(future_runs) - 1,
            )
            job.next_run = run_at
            self._jobs.append(job)

        self._scheduled_for = target_date
        scheduled_times = [run_at.strftime("%H:%M") for _, run_at in future_runs]
        logging.info(
            f"已为 {target_date.isoformat()} 抽取每日抓取偏移 {offset_minutes:+d} 分钟，"
            f"本次进程后续实际时间={' 和 '.join(scheduled_times)}。"
        )
        return [run_at for _, run_at in future_runs]

    def _run_once(self, target_date: date, run_index: int, run_at: datetime, is_last: bool):
        if self.now() - run_at > timedelta(hours=6):
            logging.warning(
                f"跳过延迟超过 6 小时的 {target_date.isoformat()} 第 {run_index} 次每日抓取任务。"
            )
        else:
            self.job_func(*self.job_args)
        if is_last:
            self.schedule_day(target_date + timedelta(days=1))
        return schedule.CancelJob

    def clear(self) -> None:
        for job in self._jobs:
            self.scheduler.cancel_job(job)
        self._jobs = []


def main():
    global RETRY_TIMES_LIMIT
    if 'PYTHON_IN_DOCKER' not in os.environ:
        # 读取 .env 文件
        import dotenv
        dotenv.load_dotenv(verbose=True)
    if os.path.isfile('/data/options.json'):
        with open('/data/options.json') as f:
            options = json.load(f)
        try:
            for key, value in options.items():
                os.environ[key] = str(value)
            from . import const
            from .llm_config import load_llm_config
            llm_config = load_llm_config()
            const.LLM_API_KEY = llm_config.api_key
            const.LLM_BASE_URL = llm_config.base_url
            const.LLM_MODEL = llm_config.model
            logging.info(f"当前以Homeassistant Add-on 形式运行.")
        except Exception as e:
            logging.error(f"读取 options.json 文件失败，程序将退出，错误信息: {e}。")
            sys.exit()

    try:
        PHONE_NUMBER = os.getenv("PHONE_NUMBER")
        logging.info("读取环境变量 PHONE_NUMBER : ***MASKED***")
        PASSWORD = os.getenv("PASSWORD")
        HASS_URL = os.getenv("HASS_URL")
        JOB_START_TIME = os.getenv("JOB_START_TIME","07:00" )
        LOG_LEVEL = os.getenv("LOG_LEVEL","INFO")
        VERSION = os.getenv("VERSION")
        RETRY_TIMES_LIMIT = int(os.getenv("RETRY_TIMES_LIMIT", 5))
        REPUBLISH_INTERVAL_MINUTES = int(os.getenv("REPUBLISH_INTERVAL_MINUTES", 15))
        SGCC_DAILY_RUNS = int(os.getenv("SGCC_DAILY_RUNS", "1"))

        logger_init(LOG_LEVEL)
        logging.info(f"当前以Docker镜像方式运行。")
    except Exception as e:
        logging.error(f"读取 .env 文件失败，程序将退出，错误信息: {e}。")
        sys.exit()

    logging.info(f"当前仓库版本为 {VERSION}，仓库地址为 https://github.com/MaribelHearm/sgcc-home-assistant-bridg")
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"当前日期为 {current_datetime}。")

    logging.info(f"开始初始化 ErrorWatcher")
    ErrorWatcher.init(root_dir='/data/errors')
    logging.info(f'ErrorWatcher 初始化完成！')
    config = FetcherConfig.from_env()
    fetcher = DataFetcher(PHONE_NUMBER, PASSWORD)
    updator = SensorUpdator() if config.PUBLISHER in {"rest", "both"} else None

    jitter_minutes = _daily_jitter_minutes()
    masked_phone = DataFetcher._mask_secret(PHONE_NUMBER)
    logging.info(
        f"当前登录用户名为 {masked_phone}，Home Assistant 地址为 {HASS_URL}。"
        f"每日抓取基准时间={JOB_START_TIME}，每日会重新从 ±{jitter_minutes} 分钟窗口抽取偏移。"
    )

    daily_scheduler = DailyJitterScheduler(
        schedule,
        JOB_START_TIME,
        jitter_minutes,
        SGCC_DAILY_RUNS,
        safe_scheduled_job,
        run_task,
        fetcher,
        "schedule",
    )
    daily_scheduler.schedule_day()
    if SGCC_DAILY_RUNS >= 2:
        logging.info("立即执行任务！持续运行期间每天重新抽取偏移，当天两次任务保持 12 小时间隔。")
    else:
        logging.info("立即执行任务！持续运行期间每天重新抽取偏移；无人值守模式默认不安排晚间第二次登录。")

    # 定期重发数据，防止HA重启后数据丢失
    # 如果缓存数据日期与当前日期不一致，则从国家电网重新获取数据
    schedule.every(REPUBLISH_INTERVAL_MINUTES).minutes.do(safe_scheduled_job, republish_or_fetch, updator, fetcher, config)

    # 启动时先尝试从缓存恢复
    # 如果缓存恢复成功，则跳过本次启动时的实时抓取，避免频繁重启导致账号被封
    if not republish_cached(updator, config):
        if has_recent_cached_business_data(updator, config):
            logging.warning(
                "启动时发现有效缓存，但重发布未完全成功；跳过启动抓取以保护账号，等待下轮发布重试。"
            )
        else:
            logging.info("未找到有效缓存，正在从国家电网获取数据...")
            run_task(fetcher, "startup")
    else:
        logging.info("已从缓存恢复数据，跳过启动时抓取以保护账号。")

    while True:
        schedule.run_pending()
        time.sleep(1)


def safe_scheduled_job(job_func, *args, **kwargs):
    try:
        return job_func(*args, **kwargs)
    except Exception as e:
        logging.error(f"定时任务 {getattr(job_func, '__name__', repr(job_func))} 执行失败，已跳过本次并继续调度: {redact_text(e)}")
        return None


def republish_or_fetch(updator: SensorUpdator | None, fetcher: DataFetcher, config: FetcherConfig):
    if not republish_cached(updator, config):
        if has_recent_cached_business_data(updator, config):
            logging.warning(
                "缓存数据仍然有效，但发布到 Home Assistant/MQTT 未完全成功；"
                "本轮不触发国网登录，避免因发布端故障放大验证码/风控。"
            )
            return
        if env_bool("SGCC_LOGIN_COOLDOWN_ENABLED", True):
            cooldown = get_login_cooldown()
            if cooldown.active:
                logging.warning(
                    f"缓存重发布未完全成功，但登录风控冷却中，剩余 "
                    f"{cooldown.remaining_seconds // 60} 分钟；本轮不触发国网登录。"
                )
                return
        logging.info("缓存数据已过期或不存在，正在从国家电网获取数据...")
        run_task(fetcher, "schedule")


def republish_cached(updator: SensorUpdator | None, config: FetcherConfig) -> bool:
    """Republish cached data to the configured HA publishers.

    REST uses the legacy SensorUpdator cache path. MQTT Discovery needs the
    normalized SQLite AccountData, otherwise a restart would not create MQTT
    discovery entities until the next live SGCC fetch.
    """
    publisher = config.PUBLISHER
    if publisher not in {"rest", "mqtt", "both"}:
        logging.warning(f"未知 PUBLISHER={publisher}，回退为 mqtt。")
        publisher = "mqtt"

    rest_ok = True
    mqtt_ok = True
    attempted = False
    if publisher in {"rest", "both"}:
        attempted = True
        if updator is None:
            logging.warning("REST 发布已启用但 SensorUpdator 未初始化。")
            rest_ok = False
        else:
            rest_ok = bool(updator.republish())

    if publisher in {"mqtt", "both"}:
        attempted = True
        mqtt_ok = republish_mqtt_from_store(config)
        if not mqtt_ok and updator is not None:
            mqtt_ok = republish_mqtt_from_legacy_ha_state(updator, config)

    return attempted and rest_ok and mqtt_ok


def has_recent_cached_business_data(updator: SensorUpdator | None, config: FetcherConfig) -> bool:
    """Return True when local cache is useful/fresh enough that a live SGCC login is not helpful.

    This is intentionally independent from publisher success. If HA REST/MQTT
    publishing fails while cache is still fresh, retrying SGCC login would only
    amplify captcha/risk-control pressure.
    """
    publisher = config.PUBLISHER
    if publisher not in {"rest", "mqtt", "both"}:
        publisher = "mqtt"

    mqtt_recent = _store_has_recent_business_data(config) if publisher in {"mqtt", "both"} else True
    rest_recent = (
        _legacy_cache_has_today_business_data(updator, config)
        if publisher in {"rest", "both"} and updator is not None
        else publisher == "mqtt"
    )
    return mqtt_recent and rest_recent


def _store_has_recent_business_data(config: FetcherConfig) -> bool:
    try:
        with Store() as store:
            account_nos = store.list_account_nos(active_only=True)
            if not account_nos:
                return False
            ignored_accounts = set(config.IGNORE_USER_ID or [])
            for account_no in account_nos:
                if account_no in ignored_accounts:
                    continue
                data = store.get_account_data(account_no)
                if data is None:
                    continue
                if not account_data_has_recent_cache_value(data):
                    return False
            return True
    except Exception as e:
        logging.warning(f"检查 SQLite Store 缓存新鲜度失败: {redact_text(e)}")
        return False


def _legacy_cache_has_today_business_data(updator: SensorUpdator, config: FetcherConfig) -> bool:
    cache_file = updator._get_cache_file()
    if not os.path.exists(cache_file):
        return False
    try:
        with open(cache_file, "r") as f:
            data = json.load(f)
    except Exception as e:
        logging.warning(f"检查旧 REST 缓存新鲜度失败: {redact_text(e)}")
        return False

    today_str = datetime.now().strftime("%Y-%m-%d")
    valid_items = 0
    ignored_accounts = set(config.IGNORE_USER_ID or [])
    for user_id, values in data.items():
        if str(user_id) in ignored_accounts:
            continue
        if not isinstance(values, dict):
            continue
        cache_timestamp = values.get("timestamp", "")
        cache_date = cache_timestamp[:10] if cache_timestamp else ""
        if cache_date != today_str:
            return False
        if has_useful_legacy_cache_entry(values):
            valid_items += 1
    return valid_items > 0


def republish_mqtt_from_store(config: FetcherConfig) -> bool:
    try:
        with Store() as store:
            ignored_accounts = set(config.IGNORE_USER_ID or [])
            active_account_nos = store.list_account_nos(active_only=True)
            inactive_account_nos = store.list_account_nos(active_only=False)
            publish_account_nos = [
                account_no
                for account_no in active_account_nos
                if account_no not in ignored_accounts
            ]
            cleanup_account_nos = sorted(
                set(inactive_account_nos)
                | {account_no for account_no in active_account_nos if account_no in ignored_accounts}
            )
            if not publish_account_nos and not cleanup_account_nos:
                logging.info("SQLite Store 中没有账户缓存，跳过 MQTT 重发布。")
                return False
            with MqttPublisher(config) as publisher:
                if not publisher.connected:
                    return False
                ok = True
                all_recent = True
                published_count = 0
                cleanup_count = 0
                for account_no in cleanup_account_nos:
                    data = store.get_account_data(account_no)
                    if data is None:
                        continue
                    if publisher.remove_account_data(data):
                        cleanup_count += 1
                    else:
                        ok = False
                if cleanup_count:
                    logging.info(f"MQTT 已从 SQLite 缓存清理 {cleanup_count} 个失效/忽略户号。")

                for account_no in publish_account_nos:
                    data = store.get_account_data(account_no)
                    if data is None:
                        continue
                    masked_account = mask_account_no(account_no)
                    if not has_useful_account_data(data):
                        logging.warning(
                            f"SQLite Store 缓存户号 {masked_account} 没有有效国网业务数据，跳过 MQTT 重发布。"
                        )
                        ok = False
                        continue
                    if not account_data_has_recent_cache_value(data):
                        logging.info(
                            f"SQLite Store 缓存户号 {masked_account} 日用电/余额数据不够新，仍先发布已有缓存并等待真实抓取刷新。"
                        )
                        all_recent = False
                    if publisher.publish_account_data(data):
                        published_count += 1
                    else:
                        ok = False
                logging.info(f"MQTT 已从 SQLite 缓存重发布 {published_count} 个户号。")
                return ok and all_recent and published_count > 0
    except Exception as e:
        logging.warning(f"MQTT 缓存重发布失败，已忽略: {redact_text(e)}")
        return False


def republish_mqtt_from_legacy_ha_state(updator: SensorUpdator | None, config: FetcherConfig) -> bool:
    """Fallback MQTT discovery from existing HA REST sensor states.

    Older deployments have useful same-day ``sgcc_cache.json`` + HA REST
    states, but no normalized SQLite Store yet. Publishing MQTT discovery from
    those states lets HA create MQTT entities immediately after the P8 rollout,
    without forcing another SGCC browser login.
    """
    if updator is None:
        logging.info("REST 状态读取器未初始化，跳过 MQTT 旧 HA 状态兜底重发布。")
        return False

    account_nos = _legacy_cache_account_nos(updator)
    if not account_nos:
        logging.info("未找到当天旧 REST 缓存户号，跳过 MQTT 旧 HA 状态兜底重发布。")
        return False

    try:
        with MqttPublisher(config) as publisher:
            if not publisher.connected:
                return False
            published_count = 0
            for account_no in account_nos:
                account_data = _account_data_from_ha_states(updator, account_no)
                if account_data is None:
                    continue
                if publisher.publish_account_data(account_data):
                    published_count += 1
            if published_count:
                logging.info(f"MQTT 已从旧 HA REST 状态兜底重发布 {published_count} 个户号。")
            return published_count > 0
    except Exception as e:
        logging.warning(f"MQTT 旧 HA 状态兜底重发布失败，已忽略: {redact_text(e)}")
        return False


def _legacy_cache_account_nos(updator: SensorUpdator) -> list[str]:
    cache_file = updator._get_cache_file()
    if not os.path.exists(cache_file):
        return []
    try:
        with open(cache_file, "r") as f:
            data = json.load(f)
    except Exception as e:
        logging.warning(f"加载旧 REST 缓存失败，跳过 MQTT 兜底: {redact_text(e)}")
        return []

    today_str = datetime.now().strftime("%Y-%m-%d")
    account_nos: list[str] = []
    for user_id, values in data.items():
        if not isinstance(values, dict):
            continue
        cache_timestamp = values.get("timestamp", "")
        cache_date = cache_timestamp[:10] if cache_timestamp else ""
        if cache_date != today_str:
            continue
        if not has_useful_legacy_cache_entry(values):
            logging.info(f"旧 REST 缓存用户 {str(user_id)[-4:]} 没有有效国网业务数据，跳过 MQTT 兜底重发布。")
            continue
        account_no = str(user_id).strip()
        if len(account_no) != 13 or not account_no.isdigit():
            logging.warning("旧 REST 缓存包含非完整户号键，无法建立稳定实体身份，跳过该条目。")
            continue
        if account_no not in account_nos:
            account_nos.append(account_no)

    suffix_counts: dict[str, int] = {}
    for account_no in account_nos:
        suffix = account_no[-4:]
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
    ambiguous_suffixes = {
        suffix for suffix, count in suffix_counts.items() if count > 1
    }
    for suffix in sorted(ambiguous_suffixes):
        logging.warning(
            f"旧 REST 实体后缀 ****{suffix} 对应多个完整户号，历史状态不可区分；"
            "跳过旧状态兜底并转真实国网抓取。"
        )
    return [
        account_no
        for account_no in account_nos
        if account_no[-4:] not in ambiguous_suffixes
    ]


def _account_data_from_ha_states(updator: SensorUpdator, account_no: str) -> AccountData | None:
    if len(account_no) != 13 or not account_no.isdigit():
        return None
    suffix = f"_{account_no[-4:]}"
    states = {
        "balance": _state_float(updator.get_sensor_state(BALANCE_SENSOR_NAME + suffix)),
        "prepay_balance": _state_float(updator.get_sensor_state(PREPAY_BALANCE_SENSOR_NAME + suffix)),
        "last_daily_usage": _state_float(updator.get_sensor_state(DAILY_USAGE_SENSOR_NAME + suffix)),
        "month_usage": _state_float(updator.get_sensor_state(MONTH_USAGE_SENSOR_NAME + suffix)),
        "month_charge": _state_float(updator.get_sensor_state(MONTH_CHARGE_SENSOR_NAME + suffix)),
        "month_valley": _state_float(updator.get_sensor_state(MONTH_VALLEY_SENSOR_NAME + suffix)),
        "month_flat": _state_float(updator.get_sensor_state(MONTH_FLAT_SENSOR_NAME + suffix)),
        "month_peak": _state_float(updator.get_sensor_state(MONTH_PEAK_SENSOR_NAME + suffix)),
        "month_tip": _state_float(updator.get_sensor_state(MONTH_TIP_SENSOR_NAME + suffix)),
        "year_usage": _state_float(updator.get_sensor_state(YEARLY_USAGE_SENSOR_NAME + suffix)),
        "year_charge": _state_float(updator.get_sensor_state(YEARLY_CHARGE_SENSOR_NAME + suffix)),
    }
    if all(value is None for value in states.values()):
        return None

    now = datetime.now()
    balance = None
    if states["balance"] is not None or states["prepay_balance"] is not None:
        balance = Balance(
            account_no=account_no,
            observed_at=now.isoformat(),
            balance_cny=states["balance"],
            prepay_balance_cny=states["prepay_balance"],
        )

    daily = []
    if (
        states["last_daily_usage"] is not None
        or states["month_valley"] is not None
        or states["month_flat"] is not None
        or states["month_peak"] is not None
        or states["month_tip"] is not None
    ):
        daily.append(DailyReading(
            account_no=account_no,
            date=now.strftime("%Y-%m-%d"),
            total_usage_kwh=states["last_daily_usage"],
            valley_usage_kwh=states["month_valley"],
            flat_usage_kwh=states["month_flat"],
            peak_usage_kwh=states["month_peak"],
            tip_usage_kwh=states["month_tip"],
        ))

    monthly = []
    if states["month_usage"] is not None or states["month_charge"] is not None:
        monthly.append(MonthlyReading(
            account_no=account_no,
            year_month=now.strftime("%Y-%m"),
            total_usage_kwh=states["month_usage"],
            total_charge_cny=states["month_charge"],
        ))

    yearly = None
    if states["year_usage"] is not None or states["year_charge"] is not None:
        yearly = YearlyReading(
            account_no=account_no,
            year=now.strftime("%Y"),
            total_usage_kwh=states["year_usage"],
            total_charge_cny=states["year_charge"],
        )

    return AccountData(
        account=Account(account_no=account_no),
        balance=balance,
        yearly=yearly,
        monthly=monthly,
        daily=daily,
    )


def _state_float(state_obj) -> float | None:
    if not state_obj:
        return None
    value = state_obj.get("state")
    if value in (None, "", "unknown", "unavailable"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _retry_backoff_seconds(retry_times: int) -> float:
    base = float(os.getenv("SGCC_RETRY_BACKOFF_SECONDS", "30"))
    max_seconds = float(os.getenv("SGCC_RETRY_BACKOFF_MAX_SECONDS", "300"))
    jitter = float(os.getenv("SGCC_RETRY_BACKOFF_JITTER_SECONDS", "10"))
    delay = min(max_seconds, base * (2 ** max(0, retry_times - 1)))
    return delay + random.uniform(0, jitter)


def run_task(data_fetcher: DataFetcher, trigger_type: str = "manual"):
    for retry_times in range(1, RETRY_TIMES_LIMIT + 1):
        try:
            current_trigger_type = trigger_type if retry_times == 1 else "retry"
            result = data_fetcher.fetch(trigger_type=current_trigger_type)
            if result in {"skipped_busy", "skipped_cooldown"}:
                return
            return
        except NonRetryableFetchError as e:
            logging.error(
                f"状态刷新任务遇到不可立即重试的失败，已停止本轮重试: "
                f"[{data_fetcher._redact_text(e)}]"
            )
            return
        except Exception as e:
            remaining = RETRY_TIMES_LIMIT - retry_times
            logging.error(f"状态刷新任务失败，原因是 [{data_fetcher._redact_text(e)}]，还剩 {remaining} 次重试机会。")
            if remaining > 0:
                delay = _retry_backoff_seconds(retry_times)
                logging.info(f"将在 {delay:.1f} 秒后重试，降低连续登录/验证码风控概率。")
                time.sleep(delay)
            continue

def logger_init(level: str):
    logger = logging.getLogger()
    logger.setLevel(level)
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)
    format = logging.Formatter("%(asctime)s  [%(levelname)-8s] ---- %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setFormatter(format)
    logger.addHandler(sh)


if __name__ == "__main__":
    main()
