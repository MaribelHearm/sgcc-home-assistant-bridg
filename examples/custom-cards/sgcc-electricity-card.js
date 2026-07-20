class SgccElectricityCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.history_entity) {
      throw new Error("sgcc-electricity-card requires history_entity");
    }
    this.config = {
      title: "国网电费",
      account_label: "户号 ****0123",
      daily_days: 31,
      monthly_months: 12,
      ...config,
    };
    this._monthOffset = 0;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 8;
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const data = buildSgccCardData(this._hass, this.config, this._monthOffset);
    this.shadowRoot.innerHTML = `${styles()}${renderCard(data, this.config)}`;
    this.shadowRoot.querySelectorAll("[data-nav-month]").forEach((el) => {
      el.addEventListener("click", () => {
        this._monthOffset += Number(el.getAttribute("data-nav-month")) || 0;
        this._render();
      });
    });
    const todayBtn = this.shadowRoot.querySelector("[data-today]");
    if (todayBtn) {
      todayBtn.addEventListener("click", () => {
        this._monthOffset = 0;
        this._render();
      });
    }
  }
}

function buildSgccCardData(hass, config, monthOffset) {
  const historyEntity = hass?.states?.[config.history_entity];
  if (!historyEntity) {
    return { error: `history_entity not found: ${config.history_entity}` };
  }

  const attrs = historyEntity.attributes || {};
  const daily = normalizeDaily(attrs.daily || []);
  const monthly = normalizeMonthly(attrs.monthly || []);

  const monthUsageEntity = entity(hass, config.month_usage_entity);
  const monthChargeEntity = entity(hass, config.month_charge_entity);
  const latestDailyEntity = entity(hass, config.latest_daily_entity);
  const balanceEntity = entity(hass, config.balance_entity);
  const arrearsEntity = entity(hass, config.arrears_entity);
  const prepayEntity = entity(hass, config.prepay_entity);
  const yearUsageEntity = entity(hass, config.year_usage_entity);
  const yearChargeEntity = entity(hass, config.year_charge_entity);

  const latestDailyDate = String(
    attrs.latest_daily_date ||
    latestDailyEntity?.attributes?.date ||
    daily[daily.length - 1]?.date ||
    attrs.date ||
    ""
  ).slice(0, 10);
  const dailyMonth = latestDailyDate.slice(0, 7) || daily[daily.length - 1]?.date?.slice(0, 7) || currentMonthKey();
  const currentMonthRows = daily.filter((row) => row.date.startsWith(dailyMonth));
  const latestDaily = daily.find((row) => row.date === latestDailyDate) || daily[daily.length - 1] || null;
  const latestDailyUsage = stateNumber(latestDailyEntity, latestDaily?.usage_kwh ?? null);
  const currentUsage = round2(sum(currentMonthRows, "usage_kwh"));

  const settledMonth = String(
    monthUsageEntity?.attributes?.month ||
    monthChargeEntity?.attributes?.month ||
    attrs.latest_month ||
    monthly[monthly.length - 1]?.month ||
    ""
  ).slice(0, 7);
  const settledMonthly = monthly.find((row) => row.month === settledMonth) || monthly[monthly.length - 1] || null;
  const settledUsage = stateNumber(monthUsageEntity, settledMonthly?.usage_kwh ?? null);
  const settledCharge = stateNumber(monthChargeEntity, settledMonthly?.charge_cny ?? null);

  const selectedMonth = addMonths(config.month || dailyMonth || settledMonth || currentMonthKey(), monthOffset);
  const selectedMonthRows = daily.filter((row) => row.date.startsWith(selectedMonth));
  const selectedMonthSummary = getMonthSummary(selectedMonth, monthly, selectedMonthRows);

  const year = (dailyMonth || currentMonthKey()).slice(0, 4);
  const yearUsage = stateNumber(yearUsageEntity, number(attrs.year_usage_kwh ?? attrs.yearly_usage_kwh, null));
  const yearCharge = stateNumber(yearChargeEntity, number(attrs.year_charge_cny ?? attrs.yearly_charge_cny, null));
  const yearSummary = {
    year,
    usage_kwh: yearUsage ?? round2(sum(monthly.filter((row) => row.month.startsWith(year)), "usage_kwh")),
    charge_cny: yearCharge ?? round2(sum(monthly.filter((row) => row.month.startsWith(year)), "charge_cny")),
  };

  const tou = buildTou(hass, config, currentMonthRows, selectedMonthSummary);
  const dailyChartRows = currentMonthRows.slice(-Number(config.daily_days || 31));
  const monthlyChartRows = monthly.slice(-Number(config.monthly_months || 12));

  return {
    title: config.title || "国网电费 · 用电监控",
    accountLabel: config.account_label || accountLabelFrom(historyEntity) || "国网电费",
    historyEntity,
    historyEntityId: config.history_entity,
    date: latestDailyDate || historyEntity.last_updated || "",
    daily,
    monthly,
    dailyMonth,
    latestDaily,
    latestDailyUsage,
    currentMonthRows,
    currentUsage,
    selectedMonth,
    selectedMonthRows,
    selectedMonthSummary,
    settledMonth,
    settledUsage,
    settledCharge,
    balance: stateNumber(balanceEntity, null),
    arrears: stateNumber(arrearsEntity, null),
    prepay: stateNumber(prepayEntity, null),
    yearSummary,
    tou,
    dailyChartRows,
    monthlyChartRows,
  };
}

function entity(hass, entityId) {
  if (!entityId) return null;
  return hass?.states?.[entityId] || null;
}

function accountLabelFrom(historyEntity) {
  const name = historyEntity?.attributes?.friendly_name || "";
  const m = name.match(/\*+\d{4}/);
  return m ? `户号 ${m[0]}` : "";
}

function normalizeDaily(rows) {
  if (!Array.isArray(rows)) return [];
  return rows
    .map((row) => ({
      date: String(row?.date || row?.day || "").slice(0, 10),
      usage_kwh: number(row?.usage_kwh ?? row?.dayEleNum),
      tip_kwh: number(row?.tip_kwh ?? row?.dayTPq),
      peak_kwh: number(row?.peak_kwh ?? row?.dayPPq),
      flat_kwh: number(row?.flat_kwh ?? row?.dayNPq),
      valley_kwh: number(row?.valley_kwh ?? row?.dayVPq),
    }))
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function normalizeMonthly(rows) {
  if (!Array.isArray(rows)) return [];
  return rows
    .map((row) => ({
      month: String(row?.month || row?.year_month || "").slice(0, 7),
      usage_kwh: number(row?.usage_kwh ?? row?.monthEleNum),
      charge_cny: number(row?.charge_cny ?? row?.monthEleCost),
      begin_date: row?.begin_date || "",
      end_date: row?.end_date || "",
    }))
    .filter((row) => /^\d{4}-\d{2}$/.test(row.month))
    .sort((a, b) => a.month.localeCompare(b.month));
}

function buildTou(hass, config, currentRows, selectedSummary) {
  const fallback = {
    valley: round2(sum(currentRows, "valley_kwh")),
    flat: round2(sum(currentRows, "flat_kwh")),
    peak: round2(sum(currentRows, "peak_kwh")),
    tip: round2(sum(currentRows, "tip_kwh")),
  };
  if (!currentRows.length && selectedSummary) {
    fallback.valley = selectedSummary.valley_kwh;
    fallback.flat = selectedSummary.flat_kwh;
    fallback.peak = selectedSummary.peak_kwh;
    fallback.tip = selectedSummary.tip_kwh;
  }
  const ids = config.tou_entities || {};
  return [
    { key: "valley", label: "谷", color: "#5e81ac", value: stateNumber(entity(hass, ids.valley), fallback.valley) },
    { key: "flat", label: "平", color: "#81a1c1", value: stateNumber(entity(hass, ids.flat), fallback.flat) },
    { key: "peak", label: "峰", color: "#ebcb8b", value: stateNumber(entity(hass, ids.peak), fallback.peak) },
    { key: "tip", label: "尖", color: "#b48ead", value: stateNumber(entity(hass, ids.tip), fallback.tip) },
  ];
}

function getMonthSummary(month, monthlyRows, dailyRows) {
  const monthly = monthlyRows.find((row) => row.month === month);
  if (monthly) {
    return {
      ...monthly,
      ...sumTou(dailyRows),
    };
  }
  return {
    month,
    usage_kwh: round2(sum(dailyRows, "usage_kwh")),
    charge_cny: null,
    ...sumTou(dailyRows),
  };
}

function sumTou(rows) {
  return {
    tip_kwh: round2(sum(rows, "tip_kwh")),
    peak_kwh: round2(sum(rows, "peak_kwh")),
    flat_kwh: round2(sum(rows, "flat_kwh")),
    valley_kwh: round2(sum(rows, "valley_kwh")),
  };
}

function renderCard(data, config) {
  if (data.error) return `<ha-card><div class="sgcc-error">${escapeHtml(data.error)}</div></ha-card>`;
  const variant = config.variant === "xiaoshi-original"
    ? "variant-xiaoshi-original"
    : config.variant === "xiaoshi"
      ? "variant-xiaoshi"
      : "variant-default";
  return `
    <ha-card class="sgcc-card">
      <article class="sgcc-widget ${variant}">
        ${renderHeader(data)}
        ${renderSettledBill(data)}
        ${renderBalanceRow(data)}
        ${renderCurrentRun(data)}
        ${renderDailyChart(data)}
        ${renderMonthlyChart(data)}
        ${renderTouBar(data)}
        ${renderAnnual(data)}
        ${renderCalendar(data, config)}
      </article>
    </ha-card>
  `;
}

function renderHeader(data) {
  return `
    <header class="sgcc-head">
      <div class="sgcc-icon">⌁</div>
      <div>
        <div class="sgcc-title">${escapeHtml(data.title)}</div>
        <div class="sgcc-subtitle">${escapeHtml(data.accountLabel)} · 更新至 ${escapeHtml(data.date || "--")}</div>
      </div>
    </header>
  `;
}

function renderSettledBill(data) {
  return `
    <section class="hero">
      ${bigMetric("当期电量", data.settledUsage, "kWh", "mdi-flash", "frost", "")}
      ${bigMetric("当期电费", data.settledCharge, "元", "mdi-cash", "gold", "")}
    </section>
  `;
}

function renderBalanceRow(data) {
  const items = [];
  if (data.balance !== null) items.push(smallMetric("电费余额", data.balance, "元", "wallet", "green"));
  if (data.arrears !== null) items.push(smallMetric("应交金额", data.arrears, "元", "clock", data.arrears > 0 ? "orange" : "green"));
  if (data.prepay !== null) items.push(smallMetric("预付费余额", data.prepay, "元", "wallet", "blue"));
  return `<section class="mini-grid ${items.length > 2 ? "three" : ""}">${items.join("")}</section>`;
}

function renderCurrentRun(data) {
  return `
    <section class="section-title">
      <div>日用电量</div>
      <span>${escapeHtml(data.date || "")}</span>
    </section>
    <section class="run-grid">
      ${midMetric("当日用电", data.latestDailyUsage, "kWh", data.latestDaily?.date || data.date || "--", "bolt", "blue")}
      ${midMetric("当期电量", data.currentUsage, "kWh", data.dailyMonth || "--", "calendar", "frost")}
      ${midMetric("当期电费", "--", "元", "", "clock", "muted")}
    </section>
  `;
}

function renderAnnual(data) {
  const y = data.yearSummary.year || currentMonthKey().slice(0, 4);
  return `
    <section class="annual-grid">
      ${smallMetric(`本年电量`, data.yearSummary.usage_kwh, "kWh", "timeline", "green")}
      ${smallMetric(`本年电费`, data.yearSummary.charge_cny, "元", "cash", "gold")}
    </section>
  `;
}

function bigMetric(label, value, unit, icon, color, note) {
  return `
    <div class="big-metric ${color}">
      <div class="metric-top"><span class="fake-icon ${icon}"></span><span>${escapeHtml(label)}</span></div>
      <div class="big-value">${format(value)} <small>${escapeHtml(unit)}</small></div>
      ${note ? `<div class="metric-note">${escapeHtml(note)}</div>` : ""}
    </div>
  `;
}

function midMetric(label, value, unit, note, icon, color) {
  const valueText = typeof value === "string" ? escapeHtml(value) : format(value);
  return `
    <div class="mid-metric ${color}">
      <div class="metric-top"><span class="fake-icon ${icon}"></span><span>${escapeHtml(label)}</span></div>
      <div class="mid-value">${valueText}${unit ? ` <small>${escapeHtml(unit)}</small>` : ""}</div>
      ${note ? `<div class="metric-note">${escapeHtml(note)}</div>` : ""}
    </div>
  `;
}

function smallMetric(label, value, unit, icon, color) {
  return `
    <div class="small-metric ${color}">
      <div class="small-icon ${icon}"></div>
      <div>
        <div class="small-value">${format(value)} <small>${escapeHtml(unit)}</small></div>
        <div class="small-label">${escapeHtml(label)}</div>
      </div>
    </div>
  `;
}

function renderDailyChart(data) {
  return `
    <section class="chart-section">
      <div class="chart-title"><span>日用电量</span><em>${escapeHtml(data.dailyMonth || "--")}</em></div>
      ${data.dailyChartRows.length ? svgDailyArea(data.dailyChartRows) : `<div class="empty">暂无日用电数据</div>`}
    </section>
  `;
}

function renderMonthlyChart(data) {
  return `
    <section class="chart-section compact">
      <div class="chart-title"><span>月用电量</span><em></em></div>
      ${data.monthlyChartRows.length ? svgMonthlyBars(data.monthlyChartRows) : `<div class="empty">暂无月度数据</div>`}
    </section>
  `;
}

function renderTouBar(data) {
  const total = data.tou.reduce((acc, item) => acc + Math.max(0, number(item.value)), 0);
  const segments = data.tou.map((item) => {
    const pct = total > 0 ? Math.max(0, number(item.value)) / total * 100 : 0;
    return `<span class="tou-seg" style="width:${pct}%;background:${item.color}" title="${escapeHtml(item.label)} ${format(item.value)} kWh"></span>`;
  }).join("");
  const labels = data.tou.map((item) => `<span><i style="background:${item.color}"></i>${escapeHtml(item.label)} ${format(item.value)}</span>`).join("");
  return `
    <section class="tou-section">
      <div class="chart-title"><span>尖峰平谷</span><em></em></div>
      <div class="tou-track">${segments}</div>
      <div class="tou-labels">${labels}</div>
    </section>
  `;
}

function renderCalendar(data, config) {
  const [year, month] = data.selectedMonth.split("-").map(Number);
  const dayMap = new Map(data.selectedMonthRows.map((row) => [Number(row.date.slice(8, 10)), row]));
  const first = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const leading = (first.getDay() + 6) % 7;
  const cells = [];
  for (let i = 0; i < leading; i += 1) cells.push(`<div class="cal-cell muted"></div>`);
  for (let day = 1; day <= daysInMonth; day += 1) {
    const row = dayMap.get(day);
    cells.push(`
      <div class="cal-cell ${row ? "has-data" : ""}">
        <div class="cal-day">${day}</div>
        ${row ? `<div class="cal-usage">${format(row.usage_kwh)}</div>` : ""}
      </div>
    `);
  }
  return `
    <section class="calendar-section">
      <div class="calendar-head">
        <button data-nav-month="-1">‹</button>
        <div>${year}年 ${month}月</div>
        <button data-nav-month="1">›</button>
        <button class="today" data-today>当月</button>
      </div>
      <div class="week-row"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
      <div class="calendar-grid">${cells.join("")}</div>
      <div class="calendar-total">月电量 <b>${format(data.selectedMonthSummary.usage_kwh)}</b> kWh · 月电费 <b>${format(data.selectedMonthSummary.charge_cny)}</b> 元</div>
    </section>
  `;
}

function svgDailyArea(rows) {
  const width = 560;
  const height = 150;
  const pad = { left: 32, right: 14, top: 12, bottom: 26 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const maxUsage = Math.max(1, ...rows.map((row) => row.usage_kwh));
  const xFor = (i) => rows.length === 1 ? pad.left + plotW / 2 : pad.left + i * (plotW / (rows.length - 1));
  const yFor = (v) => pad.top + plotH - (v / maxUsage) * plotH;
  const points = rows.map((row, i) => `${round1(xFor(i))},${round1(yFor(row.usage_kwh))}`).join(" ");
  const area = `${pad.left},${pad.top + plotH} ${points} ${pad.left + plotW},${pad.top + plotH}`;
  const dots = rows.map((row, i) => `<circle cx="${round1(xFor(i))}" cy="${round1(yFor(row.usage_kwh))}" r="2.4"><title>${escapeHtml(row.date)} ${format(row.usage_kwh)} kWh</title></circle>`).join("");
  const labels = rows.filter((_, i) => rows.length <= 8 || i % Math.ceil(rows.length / 6) === 0 || i === rows.length - 1).map((row, _, arr) => {
    const i = rows.indexOf(row);
    return `<text x="${round1(xFor(i))}" y="${height - 7}" text-anchor="middle">${row.date.slice(5)}</text>`;
  }).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg daily-svg" role="img">
      <defs><linearGradient id="sgccDailyFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#88c0d0" stop-opacity="0.34"/><stop offset="100%" stop-color="#88c0d0" stop-opacity="0.02"/></linearGradient></defs>
      <line x1="${pad.left}" y1="${pad.top + plotH}" x2="${width - pad.right}" y2="${pad.top + plotH}" class="axis" />
      <polyline points="${area}" fill="url(#sgccDailyFill)" stroke="none" />
      <polyline points="${points}" fill="none" class="line frost" />
      ${dots}
      ${labels}
    </svg>
  `;
}

function svgMonthlyBars(rows) {
  const width = 560;
  const height = 130;
  const pad = { left: 32, right: 14, top: 12, bottom: 26 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const maxUsage = Math.max(1, ...rows.map((row) => row.usage_kwh));
  const step = plotW / Math.max(1, rows.length);
  const barW = Math.max(12, Math.min(30, step * 0.42));
  const bars = rows.map((row, i) => {
    const h = (row.usage_kwh / maxUsage) * plotH;
    const x = pad.left + i * step + (step - barW) / 2;
    const y = pad.top + plotH - h;
    return `<rect x="${round1(x)}" y="${round1(y)}" width="${round1(barW)}" height="${round1(h)}" rx="5"><title>${escapeHtml(row.month)} ${format(row.usage_kwh)} kWh / ${format(row.charge_cny)} 元</title></rect>`;
  }).join("");
  const labels = rows.map((row, i) => {
    const x = pad.left + i * step + step / 2;
    return `<text x="${round1(x)}" y="${height - 7}" text-anchor="middle">${row.month.slice(5)}</text>`;
  }).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg monthly-svg" role="img">
      <line x1="${pad.left}" y1="${pad.top + plotH}" x2="${width - pad.right}" y2="${pad.top + plotH}" class="axis" />
      ${bars}
      ${labels}
    </svg>
  `;
}

function styles() {
  return `
    <style>
      :host { display: block; --sgcc-snow:#d8dee9; --sgcc-muted:#8792a6; --sgcc-frost:#88c0d0; --sgcc-blue:#81a1c1; --sgcc-green:#a3be8c; --sgcc-gold:#ebcb8b; --sgcc-orange:#d08770; --sgcc-purple:#b48ead; }
      ha-card.sgcc-card { background: transparent; box-shadow: none; border: 0; color: var(--sgcc-snow); overflow: visible; }
      .sgcc-widget {
        width: min(100%, 600px);
        margin: 22px auto 28px 0;
        padding: 18px 18px 14px;
        color: var(--sgcc-snow);
        border-radius: 28px;
        border: 1px solid rgba(216,222,233,0.16);
        background:
          radial-gradient(circle at 18% 0%, rgba(136,192,208,0.14), transparent 35%),
          radial-gradient(circle at 100% 16%, rgba(180,142,173,0.10), transparent 30%),
          linear-gradient(145deg, rgba(12,19,35,0.30), rgba(6,10,20,0.20));
        backdrop-filter: blur(24px) saturate(1.35);
        -webkit-backdrop-filter: blur(24px) saturate(1.35);
        box-shadow: 0 18px 48px rgba(0,0,0,0.38), inset 0 1px 0 rgba(236,239,244,0.11);
        box-sizing: border-box;
      }
      .sgcc-widget.variant-xiaoshi {
        --sgcc-snow: #ffffff;
        --sgcc-muted: rgba(255,255,255,.66);
        --sgcc-frost: #0fccc3;
        --sgcc-blue: #07d2ff;
        --sgcc-green: #35f0a0;
        --sgcc-gold: #b58cff;
        --sgcc-orange: #ff5f7e;
        --sgcc-purple: #804aff;
        border-radius: 14px;
        border: 1px solid rgba(15,204,195,.24);
        background:
          radial-gradient(circle at 10% 0%, rgba(15,204,195,.22), transparent 34%),
          radial-gradient(circle at 100% 18%, rgba(128,74,255,.24), transparent 32%),
          linear-gradient(145deg, rgba(15,22,38,.86), rgba(6,9,20,.92));
        box-shadow: 0 14px 34px rgba(0,0,0,.36), inset 0 1px 0 rgba(255,255,255,.10);
      }
      .sgcc-widget.variant-xiaoshi .sgcc-icon,
      .sgcc-widget.variant-xiaoshi .fake-icon,
      .sgcc-widget.variant-xiaoshi .small-icon {
        background: linear-gradient(135deg, rgba(15,204,195,.20), rgba(128,74,255,.18));
      }
      .sgcc-widget.variant-xiaoshi .monthly-svg rect { fill: var(--sgcc-purple); opacity: .86; }
      .sgcc-widget.variant-xiaoshi .cal-cell.has-data { background: rgba(15,204,195,.12); }
      .sgcc-widget.variant-xiaoshi-original {
        --sgcc-snow: #ffffff;
        --sgcc-muted: rgba(255,255,255,.68);
        --sgcc-frost: #0fccc3;
        --sgcc-blue: #07d2ff;
        --sgcc-green: #0fccc3;
        --sgcc-gold: #804aff;
        --sgcc-orange: #f30660;
        --sgcc-purple: #804aff;
        width: min(100%, 500px);
        border-radius: 10px;
        border: 0;
        background: linear-gradient(145deg, rgba(32,32,38,.94), rgba(10,12,20,.96));
        box-shadow: 0 10px 26px rgba(0,0,0,.34);
      }
      .sgcc-widget.variant-xiaoshi-original .sgcc-icon,
      .sgcc-widget.variant-xiaoshi-original .fake-icon,
      .sgcc-widget.variant-xiaoshi-original .small-icon {
        background: rgba(255,255,255,.10);
      }
      .sgcc-widget.variant-xiaoshi-original .monthly-svg rect { fill: #804aff; opacity: .82; }
      .sgcc-widget.variant-xiaoshi-original .cal-cell.has-data { background: rgba(15,204,195,.10); }
      .sgcc-head { display: flex; align-items: center; gap: 12px; padding: 0 2px 10px; }
      .sgcc-icon { width: 42px; height: 42px; border-radius: 15px; display: grid; place-items: center; color: var(--sgcc-frost); font-size: 30px; font-weight: 800; background: rgba(136,192,208,0.12); box-shadow: inset 0 1px 0 rgba(236,239,244,.10); }
      .sgcc-title { font-size: 19px; font-weight: 760; letter-spacing: .01em; }
      .sgcc-subtitle, .metric-note, .bill-note, .chart-title em, .small-label { color: var(--sgcc-muted); }
      .sgcc-subtitle { font-size: 12px; margin-top: 3px; }
      .hero { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 4px; }
      .big-metric, .mid-metric, .small-metric { min-width: 0; }
      .metric-top { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--sgcc-muted); font-weight: 620; }
      .fake-icon, .small-icon { width: 22px; height: 22px; border-radius: 10px; display: inline-grid; place-items: center; background: rgba(136,192,208,0.10); }
      .fake-icon:before, .small-icon:before { font-family: sans-serif; font-size: 13px; }
      .mdi-flash:before, .bolt:before { content: "⚡"; } .mdi-cash:before, .cash:before { content: "¥"; } .wallet:before { content: "▣"; } .clock:before { content: "◷"; } .calendar:before { content: "▦"; } .timeline:before { content: "↗"; }
      .big-value { margin-top: 6px; font-size: 32px; line-height: 1.08; font-weight: 780; letter-spacing: -.02em; }
      .big-value small, .mid-value small, .small-value small { font-size: .55em; color: var(--sgcc-muted); font-weight: 650; }
      .metric-note { margin-top: 5px; font-size: 12px; }
      .frost .big-value, .frost .mid-value { color: var(--sgcc-frost); } .gold .big-value, .gold .small-value { color: var(--sgcc-gold); } .green .small-value { color: var(--sgcc-green); } .orange .small-value { color: var(--sgcc-orange); } .blue .mid-value { color: var(--sgcc-blue); } .muted .mid-value { color: var(--sgcc-muted); }
      .bill-note { font-size: 12px; padding: 2px 2px 8px; }
      .mini-grid, .annual-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
      .mini-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .small-metric { display: grid; grid-template-columns: 30px 1fr; gap: 8px; align-items: center; padding: 4px 0; }
      .small-icon { width: 30px; height: 30px; border-radius: 12px; }
      .small-value { font-size: 19px; font-weight: 780; line-height: 1.05; }
      .small-label { font-size: 11px; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .section-title { margin: 12px 2px 4px; display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
      .section-title div, .chart-title span { color: var(--sgcc-frost); font-size: 13px; font-weight: 760; letter-spacing: .06em; }
      .section-title span, .chart-title em { font-size: 12px; font-style: normal; text-align: right; }
      .run-grid { display: grid; grid-template-columns: 1.1fr 1fr .9fr; gap: 12px; margin-bottom: 4px; }
      .mid-value { margin-top: 5px; font-size: 24px; line-height: 1.1; font-weight: 780; }
      .chart-section, .tou-section, .calendar-section { padding-top: 10px; }
      .chart-title { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; padding: 0 2px 5px; }
      .chart-svg { width: 100%; height: auto; display: block; overflow: visible; }
      .axis { stroke: rgba(143,188,187,0.14); stroke-width: 1; }
      .daily-svg .line { stroke: var(--sgcc-frost); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
      .daily-svg circle { fill: var(--sgcc-frost); stroke: rgba(216,222,233,0.9); stroke-width: .9; }
      .monthly-svg rect { fill: #81a1c1; opacity: .82; }
      .chart-svg text { fill: var(--sgcc-muted); font-size: 11px; }
      .tou-track { display: flex; width: 100%; height: 9px; overflow: hidden; border-radius: 999px; background: rgba(216,222,233,0.08); box-shadow: inset 0 0 0 1px rgba(216,222,233,.06); }
      .tou-seg { display: block; min-width: 1px; opacity: .86; }
      .tou-labels { display: flex; flex-wrap: wrap; gap: 8px 12px; color: var(--sgcc-muted); font-size: 11px; margin-top: 7px; }
      .tou-labels i { width: 7px; height: 7px; display: inline-block; border-radius: 50%; margin-right: 4px; }
      .annual-grid:before { content: ""; display: block; grid-column: 1/-1; height: 1px; margin: 8px 2px 2px; background: linear-gradient(90deg, transparent, rgba(136,192,208,.22), transparent); }
      .calendar-head { display: grid; grid-template-columns: 32px 1fr 32px 50px; gap: 7px; align-items: center; color: var(--sgcc-snow); font-weight: 760; }
      .calendar-head button { height: 28px; border: 0; border-radius: 10px; color: var(--sgcc-snow); background: rgba(216,222,233,0.08); cursor: pointer; }
      .calendar-head button:hover { background: rgba(216,222,233,0.14); }
      .calendar-head div { text-align: center; }
      .week-row, .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); }
      .week-row span { text-align: center; font-size: 11px; color: var(--sgcc-muted); padding: 7px 0 5px; }
      .calendar-grid { gap: 3px; }
      .cal-cell { min-height: 38px; border-radius: 10px; padding: 3px 2px; text-align: center; background: rgba(216,222,233,0.035); color: var(--sgcc-muted); box-sizing: border-box; }
      .cal-cell.has-data { background: rgba(136,192,208,0.08); color: var(--sgcc-snow); }
      .cal-cell.muted { opacity: .18; }
      .cal-day { font-size: 11px; font-weight: 760; }
      .cal-usage { color: var(--sgcc-frost); font-size: 10px; margin-top: 3px; font-weight: 700; }
      .calendar-total { text-align: right; margin-top: 8px; color: var(--sgcc-muted); font-size: 12px; }
      .calendar-total b { color: var(--sgcc-frost); }
      .empty, .sgcc-error { padding: 18px; color: var(--sgcc-muted); }
      @media (max-width: 720px) {
        .sgcc-widget { margin: 10px 0 18px; padding: 14px 12px 10px; border-radius: 24px; }
        .hero, .mini-grid, .mini-grid.three, .annual-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .run-grid { grid-template-columns: 1fr; gap: 8px; }
        .big-value { font-size: 28px; }
        .section-title { display: block; }
        .section-title span { display: block; text-align: left; margin-top: 3px; }
        .cal-cell { min-height: 34px; border-radius: 8px; }
      }
    </style>
  `;
}

function sum(rows, key) {
  return (rows || []).reduce((acc, row) => acc + number(row?.[key]), 0);
}

function number(value, fallback = 0) {
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : fallback;
}

function stateNumber(entity, fallback = null) {
  if (!entity || ["unknown", "unavailable", "none", ""].includes(String(entity.state).toLowerCase())) return fallback;
  const n = Number.parseFloat(entity.state);
  return Number.isFinite(n) ? n : fallback;
}

function round1(value) {
  return Math.round((number(value) + Number.EPSILON) * 10) / 10;
}

function round2(value) {
  return Math.round((number(value) + Number.EPSILON) * 100) / 100;
}

function format(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  if (typeof value === "string") return value;
  const n = round2(value);
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function currentMonthKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function addMonths(monthKey, delta) {
  const [year, month] = String(monthKey || currentMonthKey()).split("-").map(Number);
  const d = new Date(year, month - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthName(monthKey) {
  const m = Number(String(monthKey || "").slice(5, 7));
  return Number.isFinite(m) && m > 0 ? `${m}月` : "--";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

if (!customElements.get("sgcc-electricity-card")) {
  customElements.define("sgcc-electricity-card", SgccElectricityCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "sgcc-electricity-card",
  name: "SGCC Electricity Card",
  description: "Nord 玻璃风格国网电费数据卡片",
  preview: true,
});
