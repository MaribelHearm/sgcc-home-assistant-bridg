import logging
import logging.config
import os
import sys
import time
import schedule
import json
import random
from error_watcher import ErrorWatcher
from sensor_updator import SensorUpdator
from datetime import datetime,timedelta
from const import *
from config import FetcherConfig
from cache_validity import has_useful_legacy_cache_entry
from data_fetcher import DataFetcher
from model import Account, AccountData, Balance, DailyReading, MonthlyReading, YearlyReading
from mqtt_publisher import MqttPublisher
from redact import redact_text
from store import Store


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
            import const
            const.LLM_API_KEY = os.getenv('LLM_API_KEY', '').strip()
            const.LLM_BASE_URL = os.getenv('LLM_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')
            const.LLM_MODEL = os.getenv('LLM_MODEL', 'doubao-seed-2-0-pro-260215')
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

        logger_init(LOG_LEVEL)
        logging.info(f"当前以Docker镜像方式运行。")
    except Exception as e:
        logging.error(f"读取 .env 文件失败，程序将退出，错误信息: {e}。")
        sys.exit()

    logging.info(f"当前仓库版本为 {VERSION}，仓库地址为 https://github.com/MaribelHearm/sgcc-electricity-arc")
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"当前日期为 {current_datetime}。")

    logging.info(f"开始初始化 ErrorWatcher")
    ErrorWatcher.init(root_dir='/data/errors')
    logging.info(f'ErrorWatcher 初始化完成！')
    config = FetcherConfig.from_env()
    fetcher = DataFetcher(PHONE_NUMBER, PASSWORD)
    updator = SensorUpdator() if config.PUBLISHER in {"rest", "both"} else None

    # 生成随机延迟时间（-10分钟到+10分钟）
    random_delay_minutes = random.randint(-10, 10)
    parsed_time = datetime.strptime(JOB_START_TIME, "%H:%M") + timedelta(minutes=random_delay_minutes)
    masked_phone = DataFetcher._mask_secret(PHONE_NUMBER)
    logging.info(f"当前登录用户名为 {masked_phone}，Home Assistant 地址为 {HASS_URL}，程序将每天在 {parsed_time.strftime('%H:%M')} 执行。")

    # 添加随机延迟
    next_run_time = parsed_time + timedelta(hours=12)

    logging.info(f'立即执行任务！下次运行时间为每天 {parsed_time.strftime("%H:%M")} 和 {next_run_time.strftime("%H:%M")}')
    schedule.every().day.at(parsed_time.strftime("%H:%M")).do(safe_scheduled_job, run_task, fetcher, "schedule")
    schedule.every().day.at(next_run_time.strftime("%H:%M")).do(safe_scheduled_job, run_task, fetcher, "schedule")

    # 定期重发数据，防止HA重启后数据丢失
    # 如果缓存数据日期与当前日期不一致，则从国家电网重新获取数据
    schedule.every(REPUBLISH_INTERVAL_MINUTES).minutes.do(safe_scheduled_job, republish_or_fetch, updator, fetcher, config)

    # 启动时先尝试从缓存恢复
    # 如果缓存恢复成功，则跳过本次启动时的实时抓取，避免频繁重启导致账号被封
    if not republish_cached(updator, config):
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
        logging.warning(f"未知 PUBLISHER={publisher}，回退为 both。")
        publisher = "both"

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
        if not mqtt_ok:
            mqtt_ok = republish_mqtt_from_legacy_ha_state(updator, config)

    return attempted and rest_ok and mqtt_ok


def republish_mqtt_from_store(config: FetcherConfig) -> bool:
    try:
        with Store() as store:
            account_rows = store.conn.execute(
                "SELECT account_no FROM accounts ORDER BY account_no"
            ).fetchall()
            if not account_rows:
                logging.info("SQLite Store 中没有账户缓存，跳过 MQTT 重发布。")
                return False
            with MqttPublisher(config) as publisher:
                if not publisher.connected:
                    return False
                ok = True
                published_count = 0
                for row in account_rows:
                    account_no = row["account_no"]
                    account = store.get_account(account_no)
                    if account is None:
                        continue
                    data = AccountData(
                        account=account,
                        balance=store.get_latest_balance(account_no),
                        yearly=(store.get_yearly(account_no, 1) or [None])[0],
                        monthly=store.get_monthly(account_no, 24),
                        daily=store.get_daily(account_no, 31),
                    )
                    if publisher.publish_account_data(data):
                        published_count += 1
                    else:
                        ok = False
                logging.info(f"MQTT 已从 SQLite 缓存重发布 {published_count} 个户号。")
                return ok and published_count > 0
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

    postfixes = _legacy_cache_postfixes(updator)
    if not postfixes:
        logging.info("未找到当天旧 REST 缓存户号，跳过 MQTT 旧 HA 状态兜底重发布。")
        return False

    try:
        with MqttPublisher(config) as publisher:
            if not publisher.connected:
                return False
            published_count = 0
            for postfix in postfixes:
                account_data = _account_data_from_ha_states(updator, postfix)
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


def _legacy_cache_postfixes(updator: SensorUpdator) -> list[str]:
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
    postfixes: list[str] = []
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
        suffix = str(user_id)[-4:]
        if len(suffix) == 4 and suffix not in postfixes:
            postfixes.append(suffix)
    return postfixes


def _account_data_from_ha_states(updator: SensorUpdator, postfix: str) -> AccountData | None:
    suffix = f"_{postfix}"
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
    account_no = f"000000000{postfix}"
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


def run_task(data_fetcher: DataFetcher, trigger_type: str = "manual"):
    for retry_times in range(1, RETRY_TIMES_LIMIT + 1):
        try:
            current_trigger_type = trigger_type if retry_times == 1 else "retry"
            result = data_fetcher.fetch(trigger_type=current_trigger_type)
            if result == "skipped_busy":
                return
            return
        except Exception as e:
            logging.error(f"状态刷新任务失败，原因是 [{data_fetcher._redact_text(e)}]，还剩 {RETRY_TIMES_LIMIT - retry_times} 次重试机会。")
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
