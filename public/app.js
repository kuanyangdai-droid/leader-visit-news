const DATA_URL = "data/visits.json";

const state = {
  records: [],
  country: "",
  date: "",
  query: "",
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function formatDate(value) {
  if (!value) return "日期未知";
  return String(value).slice(0, 10);
}

function formatDateTime(value) {
  if (!value) return "发布时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function normalize(value) {
  return String(value || "").toLowerCase();
}

function eventLabel(value) {
  const labels = {
    state_visit: "国事访问",
    official_visit: "正式访问",
    working_visit: "工作访问",
    conference_attendance: "会议出席",
    arrival: "抵达",
    departure: "启程",
    meeting: "会见",
    other: "其他",
  };
  return labels[value] || value || "其他";
}

function filteredRecords() {
  const query = normalize(state.query);
  return state.records.filter((item) => {
    if (state.country && item.country !== state.country) return false;
    if (state.date && item.visit_date !== state.date) return false;
    if (!query) return true;
    const haystack = [
      item.leader_name,
      item.leader_title,
      item.country,
      item.destination,
      item.summary,
      item.source_name,
      eventLabel(item.event_type),
    ].map(normalize).join(" ");
    return haystack.includes(query);
  });
}

function populateCountries() {
  const select = $("#countryFilter");
  const countries = [...new Set(state.records.map((item) => item.country).filter(Boolean))].sort();
  select.innerHTML = '<option value="">全部</option>' + countries
    .map((country) => `<option value="${escapeHtml(country)}">${escapeHtml(country)}</option>`)
    .join("");
}

function render() {
  const list = $("#list");
  const status = $("#status");
  const records = filteredRecords().sort((a, b) => String(b.published_at || "").localeCompare(String(a.published_at || "")));
  $("#recordCount").textContent = records.length;

  if (!records.length) {
    status.textContent = "没有符合当前筛选条件的记录。";
    list.innerHTML = '<div class="empty">暂无公开访问新闻记录</div>';
    return;
  }

  status.textContent = `按发布时间倒序显示 ${records.length} 条记录。`;
  list.innerHTML = records.map((item) => `
    <article class="visit-card">
      <div class="card-head">
        <div>
          <h2 class="leader">${escapeHtml(item.leader_name || "未识别领导人")} <span class="pill">${escapeHtml(item.leader_title || "职务未知")}</span></h2>
          <div class="meta">
            <span>${escapeHtml(item.country || "国家未知")}</span>
            <span>${escapeHtml(formatDate(item.visit_date))}</span>
            <span>${escapeHtml(item.destination || "目的地未知")}</span>
            <span>${escapeHtml(formatDateTime(item.published_at))}</span>
          </div>
        </div>
        <span class="pill">${escapeHtml(eventLabel(item.event_type))}</span>
      </div>
      <p class="summary-text">${escapeHtml(item.summary || "")}</p>
      <div class="meta">
        ${item.possibly_special_aircraft ? '<span class="pill aircraft-pill">可能涉及专机</span>' : ""}
        <span>${escapeHtml(item.source_name || "Unknown source")}</span>
        <a class="source" href="${escapeHtml(item.source_url || "#")}" target="_blank" rel="noopener noreferrer">查看原文</a>
      </div>
    </article>
  `).join("");
}

async function loadData() {
  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.records = Array.isArray(data) ? data : [];
    populateCountries();
    render();
  } catch (error) {
    $("#status").textContent = `读取 data/visits.json 失败：${error.message}`;
    $("#list").innerHTML = '<div class="empty">无法加载本地 JSON 数据</div>';
  }
}

$("#countryFilter").addEventListener("change", (event) => {
  state.country = event.target.value;
  render();
});

$("#dateFilter").addEventListener("change", (event) => {
  state.date = event.target.value;
  render();
});

$("#searchInput").addEventListener("input", (event) => {
  state.query = event.target.value;
  render();
});

loadData();
