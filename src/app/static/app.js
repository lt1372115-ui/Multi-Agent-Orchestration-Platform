/**
 * 出行简报前端逻辑。
 *
 * 数据来自后端 `/api/v1/qweather`：
 * - `GET  /weather/10d?city=&days=10` 未来十天预报（同时返回城市与经纬度）
 * - `GET  /weather/now?location=纬度,经度` 实时天气
 * - `POST /chat` 智能体流式回答（SSE，模型自行调用天气工具）
 */

const API = "/api/v1/qweather";
const CITY_STORAGE_KEY = "travel-brief:city";
const PRESET_CITIES = ["北京", "上海", "杭州", "成都", "广州", "西安", "拉萨", "三亚"];
const PROMPTS = ["现在适合出门吗？", "未来三天适合爬山吗？", "需要带伞吗？", "该怎么穿衣服？", "哪几天最适合安排户外行程？"];

const COMPASS_TEXT = {
  n: "北风",
  nne: "东北偏北风",
  ne: "东北风",
  ene: "东北偏东风",
  e: "东风",
  ese: "东南偏东风",
  se: "东南风",
  sse: "东南偏南风",
  s: "南风",
  ssw: "西南偏南风",
  sw: "西南风",
  wsw: "西南偏西风",
  w: "西风",
  wnw: "西北偏西风",
  nw: "西北风",
  nnw: "西北偏北风",
};

const state = {
  city: null,
  days: [],
  now: null,
  chatBusy: false,
};

const dom = {
  stamp: document.getElementById("stamp"),
  banner: document.getElementById("banner"),
  lookupForm: document.getElementById("lookupForm"),
  lookupBtn: document.getElementById("lookupBtn"),
  cityInput: document.getElementById("cityInput"),
  cityChips: document.getElementById("cityChips"),
  placeLine: document.getElementById("placeLine"),
  heroCity: document.getElementById("heroCity"),
  heroRegion: document.getElementById("heroRegion"),
  heroLine: document.getElementById("heroLine"),
  heroFacts: document.getElementById("heroFacts"),
  readout: document.getElementById("readout"),
  nowIcon: document.getElementById("nowIcon"),
  nowCond: document.getElementById("nowCond"),
  nowFeels: document.getElementById("nowFeels"),
  nowTemp: document.getElementById("nowTemp"),
  nowGrid: document.getElementById("nowGrid"),
  band: document.getElementById("band"),
  bandSvg: document.getElementById("bandSvg"),
  bandCols: document.getElementById("bandCols"),
  bandDays: document.getElementById("bandDays"),
  chatLog: document.getElementById("chatLog"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  chatBtn: document.getElementById("chatBtn"),
  prompts: document.getElementById("prompts"),
};

/* ------------------------------ 通用工具 ------------------------------ */

const MONTH_DAY = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric" });
const MONTH_DAY_PAD = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
});
const WEEKDAY = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", weekday: "short" });

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function num(value, fallback = null) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function round(value) {
  return Math.round(num(value, 0));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/** 把接口返回的时间戳按中国时区换算成当地日期信息。 */
function localDay(iso, index) {
  const date = iso ? new Date(iso) : new Date();
  const valid = !Number.isNaN(date.getTime());
  const target = valid ? date : new Date(Date.now() + index * 86400000);
  const today = new Date();
  return {
    monthDay: MONTH_DAY.format(target),
    padded: MONTH_DAY_PAD.format(target).replace("/", "-"),
    week: WEEKDAY.format(target),
    isToday: MONTH_DAY.format(target) === MONTH_DAY.format(today),
  };
}

function iconId(code, fallback = "i-cloud") {
  const value = num(code);
  if (value === null) return fallback;
  if (value === 100 || value === 150) return "i-sun";
  if (value >= 101 && value <= 103) return "i-cloud-sun";
  if (value === 104) return "i-cloud";
  if (value >= 200 && value <= 299) return "i-wind";
  if (value >= 300 && value <= 399) return [302, 303, 304].includes(value) ? "i-thunder" : "i-rain";
  if (value >= 400 && value <= 499) return "i-snow";
  if (value >= 500 && value <= 599) return "i-fog";
  return fallback;
}

function iconMarkup(symbolId) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><use href="#${symbolId}"></use></svg>`;
}

function weatherFamily(text) {
  const value = String(text || "");
  if (value.includes("雪")) return "雪";
  if (value.includes("雨") || value.includes("雷")) return "雨";
  if (/雾|霾|沙|尘/.test(value)) return "雾霾";
  if (value.includes("阴")) return "阴";
  if (value.includes("云")) return "多云";
  return "晴";
}

function isWetCode(code) {
  const value = num(code, 0);
  return value >= 300 && value <= 499;
}

function describeUv(value) {
  const index = num(value);
  if (index === null) return "—";
  if (index <= 2) return `${index} · 弱`;
  if (index <= 5) return `${index} · 中等`;
  if (index <= 7) return `${index} · 强`;
  if (index <= 10) return `${index} · 很强`;
  return `${index} · 极强`;
}

/** 实时降水：优先展示小时强度，其次展示累计量。 */
function currentPrecipitationText(precipitation) {
  const amount = num(precipitation?.amount?.value, 0) || 0;
  const intensity = num(precipitation?.intensity?.value, 0) || 0;
  if (intensity > 0) return `${intensity} mm/h`;
  if (amount > 0) return `${amount} mm`;
  return "无";
}

/* ------------------------------ 十天数据加工 ------------------------------ */

/** 把接口的每日数据整理成前端渲染用的扁平结构。 */
function shapeDay(raw, index) {
  const daytime = raw.daytime || {};
  const nighttime = raw.nighttime || {};
  const dayCondition = (daytime.condition || {}).text || "未知";
  const nightCondition = (nighttime.condition || {}).text || dayCondition;
  const max = round(raw.temperatureMax?.value);
  const min = round(raw.temperatureMin?.value);
  // 接口返回的降水概率是 0~1 的小数，统一换算成百分比
  const rawPop = Math.max(
    num(daytime.precipitation?.probability, 0) || 0,
    num(nighttime.precipitation?.probability, 0) || 0,
  );
  const pop = rawPop <= 1 ? rawPop * 100 : rawPop;
  const windScale = Math.max(num(daytime.wind?.scale, 0) || 0, num(nighttime.wind?.scale, 0) || 0);
  const uv = num(raw.uvIndexMax, 0) || 0;

  const wet = isWetCode(daytime.condition?.code) || isWetCode(nighttime.condition?.code) || pop >= 60;
  let score = 100;
  score -= Math.min(45, pop * 0.55);
  if (isWetCode(daytime.condition?.code)) score -= 22;
  if (isWetCode(nighttime.condition?.code)) score -= 8;
  if (max > 33) score -= (max - 33) * 4;
  if (max < 12) score -= (12 - max) * 3.5;
  if (max - min > 12) score -= 6;
  if (windScale >= 6) score -= 18;
  else if (windScale === 5) score -= 10;
  else if (windScale === 4) score -= 4;
  if (uv >= 8) score -= 8;
  else if (uv >= 6) score -= 4;

  return {
    index,
    date: localDay(raw.forecastStartTime, index),
    max,
    min,
    dayCondition,
    nightCondition,
    code: daytime.condition?.code || nighttime.condition?.code,
    pop: Math.round(pop),
    windScale,
    windCompass: daytime.wind?.direction?.compass || "",
    uv,
    wet,
    score: clamp(Math.round(score), 5, 99),
  };
}

function verdictOf(score) {
  if (score >= 78) return "宜出行";
  if (score >= 60) return "尚可";
  return "不宜";
}

/** 找出评分最高的一到两天，作为「最值得安排」的候选。 */
function bestDays(days) {
  if (!days.length) return [];
  const ranked = [...days].sort((a, b) => b.score - a.score);
  const top = ranked[0];
  if (top.score < 74) return [];
  const picked = ranked.filter((day) => day.score >= Math.max(74, top.score - 4)).slice(0, 2);
  return picked.sort((a, b) => a.index - b.index);
}

function summarize(days) {
  const buckets = new Map();
  days.forEach((day) => {
    const family = weatherFamily(day.dayCondition);
    buckets.set(family, (buckets.get(family) || 0) + 1);
  });
  const main = [...buckets.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || "晴";
  const max = Math.max(...days.map((day) => day.max));
  const min = Math.min(...days.map((day) => day.min));
  const wetCount = days.filter((day) => day.wet).length;
  return { main, max, min, wetCount };
}

function dateRangeText(days) {
  if (!days.length) return "";
  if (days.length === 1) return `${days[0].date.monthDay}日`;
  const first = days[0].date.monthDay;
  const last = days[days.length - 1].date.monthDay;
  const sameMonth = first.split("/")[0] === last.split("/")[0];
  return sameMonth ? `${first}日、${last.split("/")[1]}日` : `${first}日、${last}日`;
}

/* ------------------------------ 渲染 ------------------------------ */

function showBanner(message) {
  dom.banner.textContent = message;
  dom.banner.hidden = !message;
}

function renderChips() {
  dom.cityChips.replaceChildren(
    ...PRESET_CITIES.map((city) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = city;
      button.addEventListener("click", () => {
        dom.cityInput.value = city;
        loadCity(city);
      });
      return button;
    }),
  );
}

function renderPrompts() {
  dom.prompts.replaceChildren(
    ...PROMPTS.map((prompt) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = prompt;
      // 已经选好目的地时，把城市带进问题，模型就不必反问
      button.addEventListener("click", () => ask(withCityContext(prompt)));
      return button;
    }),
  );
}

function withCityContext(question) {
  const city = state.city?.name;
  return city ? `${city}，${question}` : question;
}

function renderHero() {
  const { city, days } = state;
  if (!city || !days.length) return;

  const stats = summarize(days);
  const best = bestDays(days);
  dom.heroCity.textContent = city.name || "目的地";
  dom.heroRegion.textContent = [city.adm1, city.country].filter(Boolean).join(" · ");

  const parts = [
    `未来十天以<em>${escapeHtml(stats.main)}</em>为主，气温 <em>${stats.min}–${stats.max}°C</em>`,
  ];
  if (stats.wetCount) parts.push(`其中 ${stats.wetCount} 天有降水`);
  parts.push(
    best.length
      ? `${dateRangeText(best)}天气最稳，适合安排户外行程`
      : stats.wetCount >= days.length / 2
        ? "降水偏多，行程建议留出机动时间"
        : "整体平稳，按计划出行即可",
  );
  dom.heroLine.innerHTML = `${parts.join("，")}。`;

  const facts = [
    `<b>${days.length}</b> 天预报`,
    `最高 <b>${stats.max}°</b>`,
    `最低 <b>${stats.min}°</b>`,
    `降水 <b>${stats.wetCount}</b> 天`,
    `宜出行 <b>${best.length}</b> 天`,
  ];
  dom.heroFacts.replaceChildren(
    ...facts.map((html) => {
      const item = document.createElement("li");
      item.innerHTML = html;
      return item;
    }),
  );
}

function renderNow() {
  const weather = state.now;
  if (!weather) {
    dom.readout.hidden = true;
    return;
  }

  const humidity = num(weather.humidity);
  const wind = weather.wind || {};
  const precipitation = weather.precipitation || {};
  const rows = [
    ["湿度", humidity === null ? "—" : `${Math.round(humidity <= 1 ? humidity * 100 : humidity)}%`],
    [
      "风",
      `${COMPASS_TEXT[String(wind.direction?.compass || "").toLowerCase()] || "风向不定"} ${wind.scale ?? "—"} 级`,
    ],
    ["风速", wind.speed?.value === undefined ? "—" : `${wind.speed.value} ${wind.speed.unit || "m/s"}`],
    ["降水", currentPrecipitationText(precipitation)],
    ["紫外线", describeUv(weather.uvIndex)],
    [
      "能见度",
      weather.visibility?.value === undefined ? "—" : `${(weather.visibility.value / 1000).toFixed(1)} km`,
    ],
    ["气压", weather.pressure?.value === undefined ? "—" : `${Math.round(weather.pressure.value)} hPa`],
    [
      "云量",
      weather.cloudCover === undefined ? "—" : `${Math.round(num(weather.cloudCover, 0) * 100)}%`,
    ],
  ];

  dom.nowIcon.innerHTML = iconMarkup(iconId(weather.condition?.code, "i-cloud"));
  dom.nowCond.textContent = weather.condition?.text || "未知";
  dom.nowTemp.textContent = round(weather.temperature?.value);
  dom.nowFeels.textContent = `体感 ${round(weather.feelsLike?.value)}°C`;
  dom.nowGrid.replaceChildren(
    ...rows.map(([label, value]) => {
      const cell = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      cell.append(dt, dd);
      return cell;
    }),
  );
  dom.readout.hidden = false;
}

/** 绘制十天温度带：SVG 负责区间与边界，HTML 列负责节点与交互。 */
function renderBand() {
  const days = state.days;
  if (!days.length) {
    dom.band.hidden = true;
    return;
  }

  const best = new Set(bestDays(days).map((day) => day.index));
  const max = Math.max(...days.map((day) => day.max));
  const min = Math.min(...days.map((day) => day.min));
  const span = Math.max(max - min, 4);
  const top = max + span * 0.16;
  const bottom = min - span * 0.16;
  const yOf = (value) => ((top - value) / (top - bottom)) * 100;
  const xOf = (index) => ((index + 0.5) / days.length) * 100;

  const highLine = days.map((day, index) => `${xOf(index).toFixed(2)},${yOf(day.max).toFixed(2)}`);
  const lowLine = days.map((day, index) => `${xOf(index).toFixed(2)},${yOf(day.min).toFixed(2)}`);
  const bandPath = `M ${highLine.join(" L ")} L ${lowLine.slice().reverse().join(" L ")} Z`;

  dom.bandSvg.innerHTML = `
    <defs>
      <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#e4562b" stop-opacity="0.20"></stop>
        <stop offset="100%" stop-color="#1f7a8c" stop-opacity="0.22"></stop>
      </linearGradient>
    </defs>
    <path d="${bandPath}" fill="url(#bandFill)"></path>
    <path d="M ${highLine.join(" L ")}" fill="none" stroke="#e4562b" stroke-width="1.6"
      vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"></path>
    <path d="M ${lowLine.join(" L ")}" fill="none" stroke="#1f7a8c" stroke-width="1.6"
      vector-effect="non-scaling-stroke" stroke-dasharray="5 5" stroke-linecap="round"></path>
  `;

  dom.bandCols.replaceChildren(
    ...days.map((day) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute(
        "aria-label",
        `${day.date.monthDay} 日 ${day.dayCondition}，${day.min} 到 ${day.max} 摄氏度，降水概率 ${day.pop}%，${verdictOf(day.score)}`,
      );
      button.innerHTML = `
        <span class="band__dot band__dot--high" style="top:${yOf(day.max).toFixed(2)}%"></span>
        <span class="band__dot band__dot--low" style="top:${yOf(day.min).toFixed(2)}%"></span>
      `;
      button.addEventListener("click", () => askDay(day));
      item.append(button);
      return item;
    }),
  );

  dom.bandDays.replaceChildren(
    ...days.map((day) => {
      const item = document.createElement("li");
      item.className = "day";
      if (day.date.isToday) item.classList.add("day--today");
      if (best.has(day.index)) item.classList.add("day--best");
      item.innerHTML = `
        <span class="day__week">${day.date.isToday ? "今天" : day.date.week}</span>
        <span class="day__date">${day.date.padded}</span>
        <span class="day__icon">${iconMarkup(iconId(day.code))}</span>
        <span class="day__temp">${day.max}°<i> / ${day.min}°</i></span>
        <span class="day__pop">${day.pop >= 10 ? `降水 ${day.pop}%` : "无降水"}</span>
        <span class="day__verdict">${best.has(day.index) ? "宜出行" : ""}</span>
      `;
      return item;
    }),
  );

  dom.band.hidden = false;
}

function renderAll() {
  renderHero();
  renderNow();
  renderBand();
}

/* ------------------------------ 数据加载 ------------------------------ */

async function requestJson(path, init) {
  // 天气数据要实时，显式绕开浏览器缓存
  const response = await fetch(path, { cache: "no-store", ...init });
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
      }
    } catch {
      /* 响应不是 JSON 时保留默认文案 */
    }
    throw new Error(detail);
  }
  return response.json();
}

async function loadCity(name) {
  const city = String(name || "").trim();
  if (!city) {
    showBanner("先填一个城市名，例如 杭州。");
    dom.cityInput.focus();
    return;
  }

  showBanner("");
  dom.lookupBtn.disabled = true;
  dom.lookupBtn.textContent = "查询中…";
  dom.stamp.textContent = `${city} · 查询中`;

  try {
    const forecast = await requestJson(`${API}/weather/10d?city=${encodeURIComponent(city)}&days=10`);
    state.city = forecast.city || null;
    state.days = (forecast.days || []).map(shapeDay);
    state.now = null;
    renderAll();

    localStorage.setItem(CITY_STORAGE_KEY, city);
    const shareUrl = new URL(location.href);
    shareUrl.searchParams.set("city", state.city?.name || city);
    history.replaceState(null, "", shareUrl);
    dom.chatInput.placeholder = `例如：${state.city?.name || city}这周末适合出门吗？`;
    dom.placeLine.textContent = [state.city?.name, state.city?.adm1].filter(Boolean).join(" · ") || city;
    dom.stamp.textContent = `${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} 更新`;

    if (state.city?.latitude !== undefined) {
      const location = `${state.city.latitude},${state.city.longitude}`;
      try {
        const now = await requestJson(`${API}/weather/now?location=${encodeURIComponent(location)}`);
        state.now = now.weather || null;
        renderNow();
      } catch (error) {
        showBanner(`实时天气暂时取不到：${error.message}。十天预报仍可查看。`);
      }
    }
  } catch (error) {
    state.city = null;
    state.days = [];
    state.now = null;
    renderAll();
    dom.placeLine.textContent = "未选择目的地";
    dom.stamp.textContent = "查询失败";
    showBanner(`没能查到「${city}」：${error.message}`);
  } finally {
    dom.lookupBtn.disabled = false;
    dom.lookupBtn.textContent = "查看天气";
  }
}

/* ------------------------------ 对话 ------------------------------ */

function scrollChat() {
  dom.chatLog.scrollTop = dom.chatLog.scrollHeight;
}

function appendBubble(kind, label) {
  const bubble = document.createElement("div");
  bubble.className = `msg msg--${kind}`;
  const head = document.createElement("p");
  head.className = "msg__head";
  head.textContent = label;
  const body = document.createElement("div");
  bubble.append(head, body);
  dom.chatLog.append(bubble);
  scrollChat();
  return { bubble, body };
}

/** 把 `{city: "杭州"}` 渲染成一行可读参数。 */
function formatArgs(args) {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args)
    .map(([key, value]) => `${key}=${value !== null && typeof value === "object" ? JSON.stringify(value) : value}`)
    .join("  ");
}

function formatElapsed(ms) {
  const value = num(ms);
  if (value === null) return "";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

/** 在回答正文上方挂一块「调用链路」，随事件逐步长出节点。 */
function createTrace(bubble, body) {
  const wrap = document.createElement("details");
  wrap.className = "trace";
  wrap.open = true;

  const head = document.createElement("summary");
  head.className = "trace__head";
  const title = document.createElement("span");
  title.className = "trace__title";
  title.textContent = "调用链路";
  const meta = document.createElement("span");
  meta.className = "trace__meta";
  meta.textContent = "进行中";
  head.append(title, meta);

  const list = document.createElement("ol");
  list.className = "trace__list";

  wrap.append(head, list);
  // 插在作者名之后、回答正文之前
  bubble.insertBefore(wrap, body);
  return { wrap, list, meta, steps: new Map() };
}

/** 刷新链路的总体状态：节点数、进行中标记、总耗时。 */
function updateTraceMeta(trace, totalMs) {
  const total = trace.list.children.length;
  const settled = trace.list.querySelectorAll(".step--ok, .step--error").length;
  const parts = [`${total} 步`];
  if (settled < total) {
    parts.push("进行中");
  } else {
    const elapsed = formatElapsed(totalMs);
    if (elapsed) parts.push(elapsed);
  }
  trace.meta.textContent = parts.join(" · ");
}

function startStep(trace, payload) {
  const item = document.createElement("li");
  item.className = `step step--${payload.kind === "tool" ? "tool" : "model"} step--running`;
  item.dataset.label = payload.label || "";

  const line = document.createElement("p");
  line.className = "step__line";
  const label = document.createElement("span");
  label.className = "step__label";
  // 工具节点进行中显示「正在查询『杭州』的实时天气…」，结束后由后端的中文动作文案替换
  label.textContent = payload.kind === "tool" ? `正在${payload.label}…` : payload.label || "模型思考";
  const time = document.createElement("span");
  time.className = "step__time";
  line.append(label, time);
  item.append(line);

  const args = formatArgs(payload.args);
  if (args) {
    const argsLine = document.createElement("p");
    argsLine.className = "step__args";
    argsLine.textContent = args;
    item.append(argsLine);
  }

  trace.list.append(item);
  trace.steps.set(payload.id, item);
}

function finishStep(trace, payload) {
  const item = trace.steps.get(payload.id);
  if (!item) return;

  item.classList.remove("step--running");
  item.classList.add(payload.status === "error" ? "step--error" : "step--ok");

  const label = item.querySelector(".step__label");
  if (label && item.dataset.label) label.textContent = item.dataset.label;

  const time = item.querySelector(".step__time");
  if (time) time.textContent = formatElapsed(payload.elapsed_ms);

  if (payload.summary) {
    const summary = document.createElement("p");
    summary.className = "step__summary";
    summary.textContent = payload.summary;
    item.append(summary);
  }

  if (payload.preview) {
    const raw = document.createElement("details");
    raw.className = "step__raw";
    const rawHead = document.createElement("summary");
    rawHead.textContent = "查看工具原始返回";
    const pre = document.createElement("pre");
    pre.textContent = payload.preview;
    raw.append(rawHead, pre);
    item.append(raw);
  }
}

/** 流结束时兜底：把还没收到结束事件的节点标成已结束。 */
function settleTrace(trace, totalMs) {
  trace.list.querySelectorAll(".step--running").forEach((node) => {
    node.classList.remove("step--running");
    node.classList.add("step--ok");
    const label = node.querySelector(".step__label");
    if (label && node.dataset.label) label.textContent = node.dataset.label;
  });
  updateTraceMeta(trace, totalMs);
}

function inlineMarkup(text) {
  return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

/** 轻量 Markdown 渲染：只处理段落、列表与加粗，先做转义避免 XSS。 */
function formatRich(text) {
  const lines = escapeHtml(text).split(/\r?\n/);
  const out = [];
  let paragraph = [];
  let list = null;

  function flushParagraph() {
    if (paragraph.length) {
      out.push(`<p>${inlineMarkup(paragraph.join("<br>"))}</p>`);
      paragraph = [];
    }
  }

  function flushList() {
    if (list) {
      out.push(`</${list}>`);
      list = null;
    }
  }

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      return;
    }
    const bullet = /^[-*·]\s+(.*)$/.exec(trimmed);
    const ordered = /^(\d+)[.、)]\s+(.*)$/.exec(trimmed);
    const heading = /^#{1,4}\s+(.*)$/.exec(trimmed);

    if (bullet) {
      flushParagraph();
      if (list !== "ul") {
        flushList();
        out.push("<ul>");
        list = "ul";
      }
      out.push(`<li>${inlineMarkup(bullet[1])}</li>`);
    } else if (ordered) {
      flushParagraph();
      if (list !== "ol") {
        flushList();
        out.push("<ol>");
        list = "ol";
      }
      out.push(`<li>${inlineMarkup(ordered[2])}</li>`);
    } else if (heading) {
      flushParagraph();
      flushList();
      out.push(`<p><strong>${inlineMarkup(heading[1])}</strong></p>`);
    } else {
      flushList();
      paragraph.push(trimmed);
    }
  });

  flushParagraph();
  flushList();
  return out.join("");
}

async function ask(question) {
  const text = String(question || "").trim();
  if (!text || state.chatBusy) return;

  state.chatBusy = true;
  dom.chatBtn.disabled = true;
  dom.chatInput.value = "";
  appendBubble("user", "你").body.textContent = text;

  const { bubble, body } = appendBubble("ai", "随行向导");
  let raw = "";
  let scheduled = false;
  let streamError = null;
  let trace = null;
  let settled = false;

  const flush = () => {
    scheduled = false;
    body.innerHTML = `${formatRich(raw)}<span class="cursor"></span>`;
    scrollChat();
  };

  /** 处理单条 SSE 事件：链路节点、回答文本、错误与结束标记。 */
  const handlePayload = (payload) => {
    if (payload.type === "step") {
      if (!trace) trace = createTrace(bubble, body);
      if (payload.phase === "start") startStep(trace, payload);
      else finishStep(trace, payload);
      updateTraceMeta(trace, null);
      scrollChat();
    } else if (payload.type === "error") {
      streamError = payload.message || "生成过程出错";
    } else if (payload.type === "content") {
      raw += payload.content || "";
      if (!scheduled) {
        scheduled = true;
        requestAnimationFrame(flush);
      }
    } else if (payload.type === "done" && trace) {
      settleTrace(trace, payload.elapsed_ms);
      settled = true;
    }
  };

  try {
    const response = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text }),
    });
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      frames.forEach((frame) => {
        const line = frame.split("\n").find((item) => item.startsWith("data:"));
        if (!line) return;
        if (!line) return;
        try {
          handlePayload(JSON.parse(line.slice(5).trim()));
        } catch {
          /* 忽略无法解析的帧 */
        }
      });
    }

    if (buffer.trim()) {
      // 处理结尾没有空行分隔的残余帧
      const line = buffer.split("\n").find((item) => item.startsWith("data:"));
      if (line) {
        try {
          handlePayload(JSON.parse(line.slice(5).trim()));
        } catch {
          /* 忽略解析失败的尾帧 */
        }
      }
    }

    if (streamError) {
      bubble.className = "msg msg--error";
      body.innerHTML = `<p>向导生成失败：${escapeHtml(streamError)}</p>`;
    } else if (raw.trim()) {
      body.innerHTML = formatRich(raw);
    } else {
      body.innerHTML = "<p>向导这次没有给出内容，换个问法再试一次。</p>";
    }
    scrollChat();
  } catch (error) {
    bubble.className = "msg msg--error";
    body.innerHTML = `<p>向导暂时联系不上（${escapeHtml(error.message)}）。请确认后端已配置 DeepSeek 密钥，并且 <code>/api/v1/qweather/chat</code> 可以访问。</p>`;
    scrollChat();
  } finally {
    if (trace && !settled) settleTrace(trace, null);
    state.chatBusy = false;
    dom.chatBtn.disabled = false;
    dom.chatInput.focus();
  }
}

function askDay(day) {
  const city = state.city?.name || dom.cityInput.value.trim() || "当地";
  const question = `${day.date.monthDay} 日在${city}，白天${day.dayCondition}、气温 ${day.min}–${day.max}°C，${day.pop}% 降水概率，适合出行吗？给我那天的安排建议。`;
  dom.chatInput.value = question;
  ask(question);
}

/* ------------------------------ 初始化 ------------------------------ */

function bindEvents() {
  dom.lookupForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadCity(dom.cityInput.value);
  });

  dom.chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(dom.chatInput.value);
  });

  dom.chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      ask(dom.chatInput.value);
    }
  });
}

function init() {
  renderChips();
  renderPrompts();
  bindEvents();

  const fromUrl = new URLSearchParams(location.search).get("city");
  const initial = fromUrl || localStorage.getItem(CITY_STORAGE_KEY);
  if (initial) {
    dom.cityInput.value = initial;
    loadCity(initial);
  }
}

init();
