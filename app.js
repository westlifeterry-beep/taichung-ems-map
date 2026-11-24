/* 臺中救護資源地圖 */
const DAYA = { name: "大雅分隊", lat: 24.22048042, lng: 120.6502286 };
const NOMINATIM = "https://nominatim.openstreetmap.org/search";
const VIEWBOX = "120.45,24.45,121.40,23.85"; // left,top,right,bottom

const state = {
  stations: null,
  hospitals: null,
  aeds: null,
  sources: null,
  casePt: null,
  caseLabel: "",
  myPt: null,
  origin: "case",
  layersOn: { stations: true, hospitals: true, aeds: true },
};

let map, layers = {}, caseMarker, meMarker;

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 3200);
}

function haversine(a, b) {
  const R = 6371000;
  const toR = (d) => d * Math.PI / 180;
  const dLat = toR(b.lat - a.lat);
  const dLng = toR(b.lng - a.lng);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toR(a.lat)) * Math.cos(toR(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

function fmtDist(m) {
  if (m < 1000) return `${Math.round(m)} 公尺`;
  return `${(m / 1000).toFixed(m < 10000 ? 2 : 1)} 公里`;
}

function gmapsDir(origin, dest, destAddr) {
  const p = new URLSearchParams({ api: "1", travelmode: "driving" });
  if (origin && Number.isFinite(origin.lat) && Number.isFinite(origin.lng)) {
    p.set("origin", `${origin.lat},${origin.lng}`);
  }
  if (dest && Number.isFinite(dest.lat) && Number.isFinite(dest.lng)) {
    p.set("destination", `${dest.lat},${dest.lng}`);
  } else if (destAddr) {
    p.set("destination", destAddr);
  }
  return `https://www.google.com/maps/dir/?${p.toString()}`;
}

function currentOrigin() {
  if (state.origin === "daya") return DAYA;
  if (state.origin === "me") return state.myPt;
  return state.casePt;
}

function pinIcon(cls) {
  return L.divIcon({
    className: "",
    html: `<div class="pin-wrap"><div class="pin ${cls}"></div></div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 22],
    popupAnchor: [0, -20],
  });
}

function stationClass(item) {
  if (item.highlight || item.name === "大雅分隊") return "daya";
  if (item.kind === "高級救護隊") return "als";
  if (item.kind === "分隊") return "station";
  return "hq";
}

function hospClass(item) {
  if (item.level_group === "重度級") return "severe";
  if (item.level_group === "中度級") return "moderate";
  return "general";
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function navButtons(dest, addr) {
  const o = currentOrigin();
  const href = gmapsDir(o, dest, addr);
  return `<div class="actions"><a class="nav-btn" href="${esc(href)}" target="_blank" rel="noopener">用 Google 地圖導航</a></div>`;
}

function stationPopup(items) {
  return items.map((it) => {
    const badge = it.highlight ? `<span class="badge daya">大雅分隊</span>` : `<span class="badge">${esc(it.kind)}</span>`;
    const dest = it.lat != null ? { lat: it.lat, lng: it.lng } : null;
    return `<div><strong>${esc(it.name)}</strong> ${badge}<br>
      <span class="meta">${esc(it.address)}${it.phone ? "　" + esc(it.phone) : ""}</span>
      ${navButtons(dest, it.address)}</div>`;
  }).join("<hr>");
}

function hospPopup(it) {
  const warn = it.coord_precision === "nearby_bus_stop"
    ? `<div class="meta"><span class="badge warn">座標為鄰近公車站</span></div>` : "";
  const dest = it.lat != null ? { lat: it.lat, lng: it.lng } : null;
  return `<div><span class="badge ${hospClass(it)}">${esc(it.level_group)}</span>
    <strong>${esc(it.name)}</strong><br>
    <span class="meta">${esc(it.address)}</span>${warn}
    ${navButtons(dest, it.address)}</div>`;
}

function aedPopup(it) {
  const dest = { lat: it.lat, lng: it.lng };
  const loc = [it.location, it.location_note, it.hours_note].filter(Boolean).join("／");
  return `<div><strong>${esc(it.name)}</strong><br>
    <span class="meta">${esc(it.district || "")} ${esc(it.address || "")}<br>${esc(loc)}</span>
    ${navButtons(dest, it.address)}</div>`;
}

function groupStations(items) {
  const mapg = new Map();
  for (const it of items) {
    if (it.lat == null || it.lng == null) continue;
    const k = `${it.lat.toFixed(6)},${it.lng.toFixed(6)}`;
    if (!mapg.has(k)) mapg.set(k, []);
    mapg.get(k).push(it);
  }
  return mapg;
}

function buildLayers() {
  layers.stations = L.layerGroup();
  const grouped = groupStations(state.stations.items);
  grouped.forEach((items) => {
    const first = items.find((x) => x.highlight) || items[0];
    const m = L.marker([first.lat, first.lng], {
      icon: pinIcon(stationClass(first)),
      zIndexOffset: first.highlight ? 800 : 400,
      title: items.map((x) => x.name).join("、"),
    }).bindPopup(() => stationPopup(items));
    m._items = items;
    layers.stations.addLayer(m);
  });

  layers.hospitals = L.layerGroup();
  for (const it of state.hospitals.items) {
    if (it.lat == null || it.lng == null) continue;
    const m = L.marker([it.lat, it.lng], {
      icon: pinIcon(hospClass(it)),
      zIndexOffset: 300,
      title: it.name,
    }).bindPopup(() => hospPopup(it));
    m._item = it;
    layers.hospitals.addLayer(m);
  }

  layers.aeds = L.markerClusterGroup({
    maxClusterRadius: 48,
    showCoverageOnHover: false,
    spiderfyOnMaxZoom: true,
    disableClusteringAtZoom: 17,
  });
  for (const it of state.aeds.items) {
    const m = L.circleMarker([it.lat, it.lng], {
      radius: 7,
      color: "#fff",
      weight: 1,
      fillColor: "#0f7a4a",
      fillOpacity: 0.9,
    }).bindPopup(() => aedPopup(it));
    m._item = it;
    layers.aeds.addLayer(m);
  }
}

function applyLayers() {
  ["stations", "hospitals", "aeds"].forEach((k) => {
    if (state.layersOn[k]) {
      if (!map.hasLayer(layers[k])) map.addLayer(layers[k]);
    } else if (map.hasLayer(layers[k])) {
      map.removeLayer(layers[k]);
    }
    document.getElementById(`chip-${k}`).classList.toggle("on", state.layersOn[k]);
  });
}

function nearest(list, pt, n, hasCoord = (x) => x.lat != null) {
  return list
    .filter(hasCoord)
    .map((it) => ({ it, dist: haversine(pt, { lat: it.lat, lng: it.lng }) }))
    .sort((a, b) => a.dist - b.dist)
    .slice(0, n);
}

function renderSheet() {
  const title = document.getElementById("sheet-title");
  const sub = document.getElementById("sheet-sub");
  const body = document.getElementById("sheet-body");
  const originRow = document.getElementById("origin-row");
  const dayaNav = document.getElementById("btn-daya-nav");
  originRow.hidden = !state.casePt;
  dayaNav.hidden = !state.casePt;
  document.querySelectorAll("#origin-row [data-origin]").forEach((b) => {
    b.classList.toggle("on", b.dataset.origin === state.origin);
  });

  if (!state.casePt) {
    title.textContent = "設定案件地點";
    sub.textContent = "可搜尋地址、使用我的位置，或直接點地圖。";
    const missingSt = (state.stations.missing_coordinates || []).map((x) =>
      `<li>${esc(x.name)}（${esc(x.address)}）— 官網地址已變更，尚未取得可確認的新址座標，可<a href="${esc(gmapsDir(null, null, x.address))}" target="_blank" rel="noopener">用地址開啟 Google 地圖</a></li>`
    ).join("");
    const missingH = (state.hospitals.missing_coordinates || []).map((x) =>
      `<li>${esc(x.name)}（${esc(x.address)}）— 開放資料沒有座標，且無法確認與官方路名相符的點位，可<a href="${esc(gmapsDir(null, null, x.address))}" target="_blank" rel="noopener">用地址開啟 Google 地圖</a></li>`
    ).join("");
    body.innerHTML = `
      <p class="hint">距離皆為直線距離，不是行車時間或實際路程。按「用 Google 地圖導航」會開啟 Google 地圖開車路線。</p>
      ${missingSt ? `<div class="group-title">暫無可靠座標的分隊</div><ul class="hint">${missingSt}</ul>` : ""}
      ${missingH ? `<div class="group-title">暫無可靠座標的醫院</div><ul class="hint">${missingH}</ul>` : ""}
    `;
    return;
  }

  title.textContent = "案件地點已設定";
  sub.textContent = state.caseLabel || `${state.casePt.lat.toFixed(5)}, ${state.casePt.lng.toFixed(5)}`;

  const st = nearest(state.stations.items, state.casePt, 5);
  const hp = nearest(state.hospitals.items, state.casePt, 5);
  const aed = nearest(state.aeds.items, state.casePt, 5);

  const stHtml = st.map(({ it, dist }) => `
    <div class="card">
      <div class="name">${it.highlight ? `<span class="badge daya">大雅</span>` : ""}<span class="badge">${esc(it.kind)}</span>${esc(it.name)}</div>
      <div class="meta">直線距離 ${fmtDist(dist)}　${esc(it.address)}${it.phone ? "　" + esc(it.phone) : ""}</div>
      ${navButtons({ lat: it.lat, lng: it.lng }, it.address)}
    </div>`).join("");

  const hpHtml = hp.map(({ it, dist }) => `
    <div class="card">
      <div class="name"><span class="badge ${hospClass(it)}">${esc(it.level_group)}</span>${esc(it.name)}
        ${it.coord_precision === "nearby_bus_stop" ? `<span class="badge warn">鄰近公車站座標</span>` : ""}</div>
      <div class="meta">直線距離 ${fmtDist(dist)}　${esc(it.address)}</div>
      ${navButtons({ lat: it.lat, lng: it.lng }, it.address)}
    </div>`).join("");

  const aedHtml = aed.map(({ it, dist }) => `
    <div class="card">
      <div class="name">${esc(it.name)}</div>
      <div class="meta">直線距離 ${fmtDist(dist)}　${esc(it.district || "")} ${esc(it.address || "")}
        ${it.location ? "<br>放置：" + esc(it.location) : ""}</div>
      ${navButtons({ lat: it.lat, lng: it.lng }, it.address)}
    </div>`).join("");

  body.innerHTML = `
    <div class="group-title">最近分隊</div>${stHtml || "<p class='hint'>沒有可計算距離的分隊點。</p>"}
    <div class="group-title">最近急救責任醫院</div>${hpHtml || "<p class='hint'>沒有可計算距離的醫院點。</p>"}
    <div class="group-title">最近 AED</div>${aedHtml || "<p class='hint'>沒有 AED 點。</p>"}
    <p class="hint">導航起點可在上方切換。若選「我的位置」但還沒授權定位，會改由 Google 地圖在手機上使用當下位置。</p>
  `;
}

function setCase(lat, lng, label) {
  state.casePt = { lat, lng };
  state.caseLabel = label || "";
  if (!caseMarker) {
    caseMarker = L.marker([lat, lng], {
      zIndexOffset: 1000,
      title: "案件地點",
    }).addTo(map);
  } else {
    caseMarker.setLatLng([lat, lng]);
  }
  caseMarker.bindPopup(`<strong>案件地點</strong><br>${esc(label || `${lat.toFixed(5)}, ${lng.toFixed(5)}`)}`);
  map.setView([lat, lng], Math.max(map.getZoom(), 14));
  renderSheet();
}

async function geocodeAddress(q) {
  const query = q.trim();
  if (!query) return;
  toast("正在搜尋地址…");
  const url = `${NOMINATIM}?${new URLSearchParams({
    q: query.includes("臺中") || query.includes("台中") ? query : `臺中市${query}`,
    format: "jsonv2",
    limit: "1",
    countrycodes: "tw",
    viewbox: VIEWBOX,
    bounded: "1",
  }).toString()}`;
  const resp = await fetch(url, { headers: { Accept: "application/json" } });
  if (!resp.ok) throw new Error(`Nominatim HTTP ${resp.status}`);
  const data = await resp.json();
  if (!data.length) {
    toast("找不到這個地址，請再試一次，或直接點地圖。");
    return;
  }
  const hit = data[0];
  setCase(parseFloat(hit.lat), parseFloat(hit.lon), hit.display_name || query);
  toast("已設定案件地點");
}

function locateMe() {
  if (!navigator.geolocation) {
    toast("這個瀏覽器不支援定位。");
    return;
  }
  toast("正在取得位置…");
  navigator.geolocation.getCurrentPosition((pos) => {
    const lat = pos.coords.latitude, lng = pos.coords.longitude;
    state.myPt = { lat, lng };
    if (!meMarker) {
      meMarker = L.circleMarker([lat, lng], {
        radius: 8, color: "#1d4ed8", weight: 2, fillColor: "#93c5fd", fillOpacity: 0.9,
      }).addTo(map).bindPopup("我的位置");
    } else meMarker.setLatLng([lat, lng]);
    if (!state.casePt) setCase(lat, lng, "我的位置");
    else {
      renderSheet();
      map.setView([lat, lng], Math.max(map.getZoom(), 14));
    }
    toast("已取得我的位置");
  }, (err) => {
    toast("無法取得位置：請允許定位權限，或改搜尋地址、點地圖。");
    console.warn(err);
  }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 10000 });
}

function renderInfo() {
  const st = state.stations, hp = state.hospitals, aed = state.aeds;
  const box = document.getElementById("info-body");
  box.innerHTML = `
    <p>這是給臺中地區使用的小原型：底圖是 OpenStreetMap（Leaflet），不需要 Google API key。導航則用 Google 地圖的免費 deep link 開啟。</p>
    <h3>圖層資料</h3>
    <ul>
      <li><strong>分隊</strong>：官方聯絡表 ${st.official_unit_count} 個單位，另加開放資料中的消防局本部，共 ${st.count} 筆；其中 ${st.with_coordinates} 筆有座標。擷取日期：${esc(st.retrieved_at)}（Asia/Taipei）。
        名稱與現行地址來自<a href="${esc(st.source_urls.official_contact_page)}" target="_blank" rel="noopener">消防局「各大隊、分隊聯絡」</a>（頁面最後異動 2023-06-15）。
        座標優先依地址比對<a href="${esc(st.source_urls.opendata_dataset)}" target="_blank" rel="noopener">「107年臺中市各消防分隊分布點位」</a>。
        石岡、大肚、犁份三分隊官網地址已變更，沒有沿用舊址座標。</li>
      <li><strong>急救責任醫院</strong>：<a href="${esc(hp.source_urls.opendata_dataset)}" target="_blank" rel="noopener">衛生局開放資料（急救責任醫院1141229.CSV）</a>共 ${hp.count} 家（重度 ${hp.by_level["重度級"] || 0}、中度 ${hp.by_level["中度級"] || 0}、一般 ${hp.by_level["一般級"] || 0}），${hp.with_coordinates} 家有座標。
        該檔沒有經緯度，座標於 ${esc(hp.retrieved_at)} 以 Nominatim 查官方名稱或地址，並核對行政區與路名。光田向上院區、東勢農民醫院目前未標點。
        光田大甲院區、國軍中清分院僅找到同路段的公車站點，已在圖上標示。</li>
      <li><strong>AED</strong>：<a href="${esc(aed.source_url)}" target="_blank" rel="noopener">衛福部醫事司公共場所 AED 位置資訊</a>（<a href="${esc(aed.download_url)}" target="_blank" rel="noopener">每日更新 CSV</a>），於 ${esc(aed.retrieved_at)} 篩選「場所縣市＝臺中市」，共 ${aed.count} 筆，全國原始 ${aed.national_row_count} 筆。</li>
    </ul>
    <h3>目前限制</h3>
    <ul>
      <li>列出的距離是直線距離，沒有即時路況或行車時間。</li>
      <li>分隊開放資料是較舊的 107 年點位；醫院座標是地理編碼結果，少數只能標到鄰近公車站。</li>
      <li>官網聯絡表最後異動為 2023-06-15，之後若單位搬遷，這裡不會自動更新。</li>
    </ul>
    <p>地圖圖磚 © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> 貢獻者。地址搜尋使用 Nominatim。</p>
  `;
}

async function loadJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

async function main() {
  L.Icon.Default.imagePath = "vendor/leaflet/images/";
  map = L.map("map", { zoomControl: true, attributionControl: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  map.setView([DAYA.lat, DAYA.lng], 12);

  try {
    const [stations, hospitals, aeds, sources] = await Promise.all([
      loadJSON("data/stations.json"),
      loadJSON("data/hospitals.json"),
      loadJSON("data/aeds.json"),
      loadJSON("data/sources.json"),
    ]);
    state.stations = stations;
    state.hospitals = hospitals;
    state.aeds = aeds;
    state.sources = sources;
  } catch (err) {
    document.getElementById("counts").textContent = "資料載入失敗";
    toast("資料檔載入失敗，請確認 data/ 資料夾是否存在。");
    console.error(err);
    return;
  }

  const sc = state.stations.with_coordinates;
  const hc = state.hospitals.with_coordinates;
  const ac = state.aeds.count;
  document.getElementById("counts").textContent =
    `分隊 ${sc} 個點 · 醫院 ${hc} 家 · AED ${ac} 處　資料擷取於 ${state.stations.retrieved_at}（臺北時間）`;
  document.getElementById("chip-stations").textContent = `分隊 ${sc}`;
  document.getElementById("chip-hospitals").textContent = `醫院 ${hc}`;
  document.getElementById("chip-aeds").textContent = `AED ${ac}`;

  buildLayers();
  applyLayers();
  renderSheet();
  renderInfo();
  window.__MAP_READY__ = {
    stations: sc,
    hospitals: hc,
    aeds: ac,
    stationItems: state.stations.items.length,
    hospitalItems: state.hospitals.items.length,
  };

  map.on("click", (e) => {
    setCase(e.latlng.lat, e.latlng.lng, "地圖點選位置");
  });

  document.getElementById("btn-search").addEventListener("click", () => {
    geocodeAddress(document.getElementById("q").value).catch((e) => {
      toast("地址搜尋失敗，請稍後再試，或改點地圖。");
      console.warn(e);
    });
  });
  document.getElementById("q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      document.getElementById("btn-search").click();
    }
  });
  document.getElementById("btn-me").addEventListener("click", locateMe);
  document.getElementById("chip-stations").addEventListener("click", () => { state.layersOn.stations = !state.layersOn.stations; applyLayers(); });
  document.getElementById("chip-hospitals").addEventListener("click", () => { state.layersOn.hospitals = !state.layersOn.hospitals; applyLayers(); });
  document.getElementById("chip-aeds").addEventListener("click", () => { state.layersOn.aeds = !state.layersOn.aeds; applyLayers(); });
  document.getElementById("origin-row").addEventListener("click", (e) => {
    const b = e.target.closest("[data-origin]");
    if (!b) return;
    state.origin = b.dataset.origin;
    if (state.origin === "me" && !state.myPt) locateMe();
    renderSheet();
  });
  document.getElementById("btn-daya-nav").addEventListener("click", () => {
    if (!state.casePt) return;
    window.open(gmapsDir(DAYA, state.casePt), "_blank", "noopener");
  });
  document.getElementById("btn-info").addEventListener("click", () => {
    document.getElementById("info-modal").classList.add("show");
  });
  document.getElementById("btn-close-info").addEventListener("click", () => {
    document.getElementById("info-modal").classList.remove("show");
  });
  document.getElementById("info-modal").addEventListener("click", (e) => {
    if (e.target.id === "info-modal") e.target.classList.remove("show");
  });
}

main();
