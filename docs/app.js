(() => {
  "use strict";

  const state = {
    items: [],
    filtered: [],
    config: null,
    view: localStorage.getItem("nb-view") || (window.matchMedia("(max-width: 780px)").matches ? "cards" : "table"),
    expandedSeries: new Set(),
    filters: {
      search: "",
      hideDedicated: true,
      cpuBrand: "",
      gpuType: "",
      brand: "",
      screenMin: null,
      refreshMin: null,
      memoryMin: null,
      storageMin: null,
      batteryMin: null,
      priceMin: null,
      priceMax: null,
    },
  };

  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const display = (value, suffix = "") =>
    value === null || value === undefined || value === "" ? "—" : `${escapeHtml(value)}${suffix}`;

  const money = (value) => {
    const number = Number(value);
    return Number.isFinite(number)
      ? `¥${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(number)}`
      : "价格待确认";
  };

  const fieldTemplates = {
    cpu_brand: () => selectField("cpuBrand", "处理器品牌", [["", "全部"], ["Intel", "Intel"], ["AMD", "AMD"]]),
    cpu_family: () => "",
    cpu_voltage_type: () => "",
    gpu_type: () => selectField("gpuType", "显卡类型", [["", "全部"], ["integrated", "集成显卡"], ["dedicated", "独立显卡"]]),
    gpu: () => checkField("hideDedicated", "默认隐藏独立显卡", true),
    screen_size: () => numberField("screenMin", "最小屏幕尺寸", "英寸", 0.1),
    resolution: () => "",
    refresh_rate: () => numberField("refreshMin", "最低刷新率", "Hz", 1),
    memory_gb: () => numberField("memoryMin", "最低内存", "GB", 1),
    storage_gb: () => numberField("storageMin", "最低存储", "GB", 1),
    numeric_keypad: () => "",
    keyboard_backlight: () => "",
    battery_wh: () => numberField("batteryMin", "最低电池容量", "Wh", 1),
    ports: () => "",
    price: () => rangeField("priceMin", "priceMax", "价格区间", "¥"),
    brand: () => selectField("brand", "品牌", [["", "全部"]]),
    numeric_keypad: () => checkField("numpadOnly", "仅数字小键盘", false),
    keyboard_backlight: () => checkField("backlightOnly", "仅键盘背光", false),
    multi_source: () => checkField("multiOnly", "仅多源交叉验证", false),
  };

  function selectField(key, label, options) {
    return `<label class="select-field"><span>${label}</span><select data-filter="${key}">${
      options.map(([value, text]) => `<option value="${escapeHtml(value)}">${escapeHtml(text)}</option>`).join("")
    }</select></label>`;
  }

  function numberField(key, label, unit, step) {
    return `<div class="field"><label for="filter-${key}">${label} · ${unit}</label>
      <input id="filter-${key}" data-filter="${key}" type="number" min="0" step="${step}" placeholder="不限"></div>`;
  }

  function rangeField(minKey, maxKey, label, unit) {
    return `<div class="field"><label>${label} · ${unit}</label><div class="range-row">
      <input data-filter="${minKey}" type="number" min="0" placeholder="最低">
      <input data-filter="${maxKey}" type="number" min="0" placeholder="最高">
    </div></div>`;
  }

  function checkField(key, label, checked) {
    return `<label class="check-row"><input data-filter="${key}" type="checkbox" ${checked ? "checked" : ""}>${label}</label>`;
  }

  function sourceBadges(item) {
    const sources = Array.isArray(item.atomic_source_names) ? item.atomic_source_names : [];
    return `<div class="source-badges ${sources.length > 1 ? "multi" : ""}">${
      sources.map((source) => `<span class="source-badge">${escapeHtml(source)}</span>`).join("")
    }</div>`;
  }

  function tags(item) {
    const values = [
      [
        item.cpu_voltage_type === "desktop_performance"
          ? "桌面级 CPU · 形态已核验"
          : "H 系",
        "performance",
      ],
      [item.dedicated_gpu ? "独显" : "集显", item.dedicated_gpu ? "dedicated" : ""],
      ["数字键盘", ""],
      ["背光", ""],
    ];
    return `<div class="tag-row">${values.map(([text, kind]) =>
      `<span class="tag ${kind}">${text}</span>`).join("")}</div>`;
  }

  function rowTemplate(item) {
    const url = item.source_url || Object.values(item.source_urls || {})[0] || "#";
    const multi = Number(item.source_count) >= 2;
    return `<tr class="${multi ? "multi-source" : ""}">
      <td><a class="model-name" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(item.title || item.model)}</a>
        <span class="subtle">${escapeHtml(item.brand || "品牌待确认")}</span>${tags(item)}</td>
      <td>${display(item.cpu)}<span class="subtle">${display(item.gpu)}</span></td>
      <td>${display(item.screen_size, "″")}<span class="subtle">${display(item.resolution)} · ${display(item.refresh_rate, "Hz")}</span></td>
      <td>${display(item.memory_gb, "GB")}<span class="subtle">${display(item.storage_gb, "GB SSD")}</span></td>
      <td><span class="price">${money(item.price)}</span><span class="subtle">参考价格</span></td>
      <td>${sourceBadges(item)}<span class="subtle">榜单 #${display(item.source_rank)}</span></td>
    </tr>`;
  }

  // SPU 级系列识别：型号剥离括号配置后缀（联想拯救者Y7000 2025(i7.../16GB...) -> 联想拯救者Y7000 2025）
  function spuIdentity(item) {
    const model = String(item.model || item.title || "");
    let base = model.split(/[（(]/)[0].trim();
    // JD 长标题无括号：截断到"品牌+型号"（取前 18 字符内最后一个空格/分隔）
    if (base === model && base.length > 18) {
      const cut = base.slice(0, 18);
      const sp = Math.max(cut.lastIndexOf(" "), cut.lastIndexOf("·"), cut.lastIndexOf("-"), cut.lastIndexOf("【"));
      if (sp > 4) base = cut.slice(0, sp).trim();
      else base = cut.trim();
    }
    const brand = String(item.brand || "").trim();
    return {
      key: "spu|" + brand + "|" + base.replace(/\s+/g, ""),
      name: base || model,
      brand: brand,
    };
  }

  function groupRowsBySpu(rows) {
    const groups = [];
    const map = new Map();
    rows.forEach((row) => {
      const id = spuIdentity(row);
      let g = map.get(id.key);
      if (!g) {
        g = { key: id.key, name: id.name, brand: id.brand, rows: [] };
        map.set(id.key, g);
        groups.push(g);
      }
      g.rows.push(row);
    });
    groups.forEach((g) => {
      g.rows.sort((a, b) => Number(a.source_rank || 9999) - Number(b.source_rank || 9999));
    });
    return groups;
  }

  function cardTemplate(item) {
    const url = item.source_url || Object.values(item.source_urls || {})[0] || "#";
    const multi = Number(item.source_count) >= 2;
    return `<article class="laptop-card ${multi ? "multi-source" : ""}">
      <div class="card-top"><div><a class="model-name" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(item.title || item.model)}</a>
      <span class="subtle">${escapeHtml(item.brand || "")} · 综合榜 #${display(item.source_rank)}</span></div>
      <span class="price">${money(item.price)}</span></div>
      ${tags(item)}
      <div class="card-specs">
        <div><span>处理器</span><strong>${display(item.cpu)}</strong></div>
        <div><span>显卡</span><strong>${display(item.gpu)}</strong></div>
        <div><span>屏幕</span><strong>${display(item.screen_size, "″")} · ${display(item.refresh_rate, "Hz")}</strong></div>
        <div><span>内存 / 存储</span><strong>${display(item.memory_gb, "GB")} / ${display(item.storage_gb, "GB")}</strong></div>
      </div>
      <div class="card-footer">${sourceBadges(item)}<a href="${escapeHtml(url)}" target="_blank" rel="noopener">查看来源 →</a></div>
    </article>`;
  }

  function renderFilterGroups() {
    const groups = state.config?.groups || [];
    $("#filter-groups").innerHTML = groups.map((group, index) => {
      const content = group.fields.map((field) => fieldTemplates[field]?.() || "").join("");
      if (!content) return "";
      return `<details class="filter-group" ${index < 3 || group.id === "price_brand" ? "open" : ""}>
        <summary>${escapeHtml(group.label)}</summary><div class="group-body">${content}</div>
      </details>`;
    }).join("");

    const brands = [...new Set(state.items.map((item) => item.brand).filter(Boolean))]
      .sort((a, b) => String(a).localeCompare(String(b), "zh-CN"));
    const brandSelect = $('[data-filter="brand"]');
    if (brandSelect) {
      brandSelect.innerHTML += brands.map((brand) =>
        `<option value="${escapeHtml(brand)}">${escapeHtml(brand)}</option>`).join("");
    }
    document.querySelectorAll("[data-filter]").forEach((input) => {
      input.addEventListener("input", onFilterChange);
      input.addEventListener("change", onFilterChange);
    });
  }

  function renderForcedFilters() {
    const forced = state.config?.forced || {};
    $("#forced-filters").innerHTML = Object.values(forced).map((rule) => {
      const value = rule.value === true
        ? "是"
        : (rule.allowed_values
          ? "H / HX / HS / HK；桌面级 CPU 仅限形态证据例外"
          : rule.value);
      return `<div class="forced-pill">${escapeHtml(rule.label)} · ${escapeHtml(value)}</div>`;
    }).join("");
  }

  function onFilterChange(event) {
    const key = event.target.dataset.filter;
    if (!key) return;
    state.filters[key] = event.target.type === "checkbox"
      ? event.target.checked
      : (event.target.type === "number" ? (event.target.value === "" ? null : Number(event.target.value)) : event.target.value);
    applyFilters();
  }

  function passesNumber(value, minimum) {
    return minimum === null || (Number.isFinite(Number(value)) && Number(value) >= minimum);
  }

  function applyFilters() {
    const f = state.filters;
    const query = f.search.trim().toLocaleLowerCase("zh-CN");
    state.filtered = state.items.filter((item) => {
      if (query && ![item.title, item.model, item.cpu, item.gpu, item.brand].join(" ").toLocaleLowerCase("zh-CN").includes(query)) return false;
      if (f.hideDedicated && item.dedicated_gpu === true) return false;
      if (f.cpuBrand && item.cpu_brand !== f.cpuBrand) return false;
      if (f.gpuType && item.gpu_type !== f.gpuType) return false;
      if (f.brand && item.brand !== f.brand) return false;
      if (!passesNumber(item.screen_size, f.screenMin)) return false;
      if (!passesNumber(item.refresh_rate, f.refreshMin)) return false;
      if (!passesNumber(item.memory_gb, f.memoryMin)) return false;
      if (!passesNumber(item.storage_gb, f.storageMin)) return false;
      if (!passesNumber(item.battery_wh, f.batteryMin)) return false;
      if (f.priceMin !== null && !(Number(item.price) >= f.priceMin)) return false;
      if (f.priceMax !== null && !(Number(item.price) <= f.priceMax)) return false;
      if (f.numpadOnly && !item.numeric_keypad) return false;
      if (f.backlightOnly && !item.keyboard_backlight) return false;
      if (f.multiOnly && !(Number(item.source_count) >= 2)) return false;
      return true;
    });
    sortItems();
    renderResults();
    updateActiveFilterCount();
  }

  function sortItems() {
    const mode = $("#sort").value;
    const large = Number.MAX_SAFE_INTEGER;
    const comparators = {
      source_rank: (a, b) => (b.source_count || 0) - (a.source_count || 0) || (a.source_rank ?? large) - (b.source_rank ?? large),
      source_count: (a, b) => (b.source_count || 0) - (a.source_count || 0) || (a.source_rank ?? large) - (b.source_rank ?? large),
      price_asc: (a, b) => (a.price ?? large) - (b.price ?? large),
      price_desc: (a, b) => (b.price ?? -1) - (a.price ?? -1),
      screen_desc: (a, b) => (parseFloat(b.screen_size) || 0) - (parseFloat(a.screen_size) || 0) || (a.source_rank ?? large) - (b.source_rank ?? large),
      refresh_desc: (a, b) => (parseFloat(b.refresh_rate) || 0) - (parseFloat(a.refresh_rate) || 0) || (a.source_rank ?? large) - (b.source_rank ?? large),
      memory_desc: (a, b) => (Number(b.memory_gb) || 0) - (Number(a.memory_gb) || 0) || (a.source_rank ?? large) - (b.source_rank ?? large),
      storage_desc: (a, b) => (Number(b.storage_gb) || 0) - (Number(a.storage_gb) || 0) || (a.source_rank ?? large) - (b.source_rank ?? large),
      numpad_first: (a, b) => (Number(b.numeric_keypad) || 0) - (Number(a.numeric_keypad) || 0) || (a.source_rank ?? large) - (b.source_rank ?? large),
      backlight_first: (a, b) => (Number(b.keyboard_backlight) || 0) - (Number(a.keyboard_backlight) || 0) || (a.source_rank ?? large) - (b.source_rank ?? large),
    };
    state.filtered.sort(comparators[mode] || comparators.source_rank);
  }

  function renderResults() {
    $("#visible-count").textContent = state.filtered.length;
    $("#laptop-rows").innerHTML = state.filtered.map(rowTemplate).join("");
    // 卡片视图 = SPU 级：按系列分组折叠，组内展开各 SKU 卡片
    const groups = groupRowsBySpu(state.filtered);
    $("#card-view").innerHTML = groups.map((g, gi) => {
      const expanded = state.expandedSeries.has(g.key);
      const detailId = "spu-models-" + gi;
      const cards = g.rows.map(cardTemplate).join("");
      return `<section class="spu-group" data-spu="${escapeHtml(g.key)}">
        <button type="button" class="spu-toggle" data-spu-key="${escapeHtml(g.key)}" aria-expanded="${expanded}" aria-controls="${detailId}">
          <span class="spu-name">${escapeHtml(g.name)}</span>
          <small class="spu-count">${g.rows.length} 个配置</small>
          <span class="spu-arrow">${expanded ? "▾" : "▸"}</span>
        </button>
        <div id="${detailId}" class="spu-models" ${expanded ? "" : "hidden"}>${cards}</div>
      </section>`;
    }).join("");
    $("#empty-state").hidden = state.filtered.length !== 0;
    $("#table-view").hidden = state.filtered.length === 0 || state.view !== "table";
    $("#card-view").hidden = state.filtered.length === 0 || state.view !== "cards";
  }

  function updateActiveFilterCount() {
    const defaults = { hideDedicated: true, search: "" };
    const count = Object.entries(state.filters).filter(([key, value]) => {
      if (key === "hideDedicated") return value !== defaults.hideDedicated;
      return value !== null && value !== "";
    }).length;
    $("#active-filter-count").textContent = count;
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".spu-toggle");
    if (!btn) return;
    const key = btn.dataset.spuKey;
    if (state.expandedSeries.has(key)) state.expandedSeries.delete(key);
    else state.expandedSeries.add(key);
    renderResults();
  });

  function setView(view) {
    state.view = view;
    try { localStorage.setItem("nb-view", view); } catch (e) { /* private mode */ }
    document.querySelectorAll("[data-view]").forEach((button) =>
      button.classList.toggle("is-active", button.dataset.view === view));
    renderResults();
  }

  function resetFilters() {
    state.filters = {
      search: "", hideDedicated: true, cpuBrand: "", gpuType: "", brand: "",
      screenMin: null, refreshMin: null, memoryMin: null, storageMin: null,
      batteryMin: null, priceMin: null, priceMax: null,
    };
    $("#search").value = "";
    document.querySelectorAll("[data-filter]").forEach((input) => {
      if (input.type === "checkbox") input.checked = input.dataset.filter === "hideDedicated";
      else input.value = "";
    });
    applyFilters();
  }

  function bindControls() {
    $("#search").addEventListener("input", (event) => {
      state.filters.search = event.target.value;
      applyFilters();
    });
    $("#sort").addEventListener("change", () => {
      sortItems();
      renderResults();
    });
    $("#reset-filters").addEventListener("click", resetFilters);
    document.querySelectorAll("[data-view]").forEach((button) =>
      button.addEventListener("click", () => setView(button.dataset.view)));
    $("#filter-toggle").addEventListener("click", () => {
      const open = $("#filter-panel").classList.toggle("is-open");
      $("#filter-toggle").setAttribute("aria-expanded", String(open));
    });
  }

  async function load() {
    bindControls();
    try {
      const [dataResponse, configResponse] = await Promise.all([
        fetch("data/latest.json", { cache: "no-cache" }),
        fetch("data/filter_conditions.json", { cache: "no-cache" }),
      ]);
      if (!dataResponse.ok || !configResponse.ok) throw new Error("发布数据文件不存在");
      const payload = await dataResponse.json();
      state.config = await configResponse.json();
      state.items = Array.isArray(payload.items) ? payload.items : [];
      state.filters.hideDedicated = state.config?.defaults?.hide_dedicated_gpu !== false;
      $("#total-count").textContent = state.items.length;
      $("#multi-count").textContent = state.items.filter((item) => Number(item.source_count) >= 2).length;
      $("#source-count").textContent = Array.isArray(payload.sources) ? payload.sources.length : 0;
      $("#freshness").textContent = payload.generated_at
        ? `更新于 ${new Date(payload.generated_at).toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" })}`
        : "已加载最新数据";
      renderForcedFilters();
      renderFilterGroups();
      $("#status").hidden = true;
      setView(state.view);
      applyFilters();
    } catch (error) {
      $("#status").textContent = `数据加载失败：${error.message}`;
      $("#status").classList.add("error");
    }
  }

  load();
})();
