# 臺中救護資源地圖（小原型）

給臺中市消防與救護出勤參考用的單一網頁地圖：可看各分隊、急救責任醫院和公共場所 AED，設定案件地點後列出最近資源，並用 Google 地圖導航。

- 底圖：Leaflet + OpenStreetMap，不需要 Google API key
- 導航：Google Maps URL（`https://www.google.com/maps/dir/?api=1&origin=...&destination=...&travelmode=driving`），不需要 API key
- 大雅分隊在地圖上特別標示

資料擷取日期：2026-11-24（Asia/Taipei）。頁面上的「說明」會列出每一層的來源網址、筆數與缺漏。

## 本機開啟

用任何靜態網站伺服器開啟（直接用檔案協定開 `index.html`，部分瀏覽器會擋 JSON 載入）：

```bash
python3 -m http.server 8765
```

然後打開 `http://127.0.0.1:8765/`。

## 資料

| 圖層 | 檔案 | 有座標筆數 | 來源 |
| --- | --- | --- | --- |
| 分隊／大隊等 | `data/stations.json` | 63／66 | 消防局官網聯絡表 + 107 年分隊點位開放資料 |
| 急救責任醫院 | `data/hospitals.json` | 21／23 | 衛生局 1141229 開放資料（名稱、地址、分級）；座標由 Nominatim 查得 |
| AED | `data/aeds.json` | 1,503 | 衛福部公共場所 AED 開放資料，篩選臺中市 |

沒有可靠座標的單位不會在地圖上標點，以免標錯位置，頁面說明裡可以用官方地址打開 Google 地圖。

重建資料：

```bash
python3 scripts/build_data.py
```

請先準備 `/tmp/taichung-raw/` 裡已下載的官方檔案，或依腳本裡的網址自行更新。

## 授權

各資料集依政府資料開放授權條款。地圖圖磚 © OpenStreetMap 貢獻者。本原型僅供參考，不能取代 119 派遣或官方系統。
