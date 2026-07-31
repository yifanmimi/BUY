import asyncio
import json
import csv
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 輔助函式：將標案資料存成 CSV 檔
# ---------------------------------------------------------------------------
def save_to_csv(data, filename, fieldnames):
    """將 list of dict 資料寫入 CSV 檔案"""
    if not data:
        return
    try:
        with open(filename, mode='w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        print(f"📁 已成功匯出檔案：{filename}")
    except Exception as e:
        print(f"❌ 寫入 {filename} 失敗: {e}")


# ---------------------------------------------------------------------------
# Playwright 抓取當日『所有頁面』的勞務類標案
# ---------------------------------------------------------------------------
async def fetch_all_daily_services():
    print("🔍 [Playwright] 開始抓取今日『所有』勞務類標案...\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        tenders = []
        try:
            # 前往招標查詢頁面
            await page.goto("https://web.pcc.gov.tw/prkms/tender/common/basic/readTenderBasic", wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)

            # 1. 勾選「當日」
            today_label = page.locator("label").filter(has_text="當日").first
            await today_label.click(force=True)

            # 2. 勾選「勞務類」
            service_label = page.locator("label[for='RadProctrgCate3'], #RadProctrgCate3").first
            await service_label.click(force=True)

            # 3. 送出查詢
            print("🚀 送出查詢，抓取今日全量勞務案...")
            search_button = page.locator("input[value='搜尋'], #btnSearch, a:has-text('搜尋')").first
            
            if await search_button.is_visible():
                await search_button.click(force=True)
            else:
                await page.evaluate("typeof query === 'function' ? query() : document.forms[0].submit();")

            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)

            # 4. 迴圈處理多頁分頁抓取
            page_num = 1
            while True:
                print(f"📄 正在解析第 {page_num} 頁...")
                content = await page.content()
                soup = BeautifulSoup(content, "html.parser")
                
                rows = soup.find_all("tr")
                page_count = 0

                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 3 and not row.find("th"):
                        links = row.find_all("a")
                        for link in links:
                            href = link.get("href", "")
                            title = link.get_text(strip=True)
                            
                            if href and any(k in href for k in ["tpam", "readDtl", "pk=", "location"]):
                                org_name = cols[1].get_text(strip=True) if len(cols) > 1 else "未知機關"
                                
                                if len(title) > 2 and title not in ["檢視", "詳細內容", "列印", "查詢", "按鈕", "下一頁", "上一頁"]:
                                    full_link = f"https://web.pcc.gov.tw{href}" if href.startswith("/") else href
                                    
                                    tenders.append({
                                        "org": org_name,
                                        "title": title,
                                        "link": full_link
                                    })
                                    page_count += 1
                                    break
                
                print(f"   └─ 第 {page_num} 頁抓取到 {page_count} 筆標案。")

                # 嘗試尋找並點擊「下一頁」按鈕
                next_button = page.locator("a:has-text('下一頁'), input[value='下一頁']").first
                if await next_button.is_visible():
                    page_num += 1
                    await next_button.click()
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(2000)
                else:
                    print("✅ 已到達最後一頁，停止抓取。")
                    break

            print(f"\n🎉 成功抓取完畢！共 {page_num} 頁，總計 {len(tenders)} 筆勞務類標案！\n" + "="*65)
            return tenders

        except Exception as e:
            print(f"❌ 抓取過程發生錯誤: {e}")
            return tenders
        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# 主程式進入點
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y%m%d")
    
    # 執行爬蟲抓取全量標案
    daily_tenders = asyncio.run(fetch_all_daily_services())
    
    if daily_tenders:
        # 存成 CSV 與 JSON 檔案
        raw_csv_filename = f"today_services_{today_str}.csv"
        raw_json_filename = f"today_services_{today_str}.json"
        
        save_to_csv(daily_tenders, raw_csv_filename, fieldnames=["org", "title", "link"])
        with open(raw_json_filename, "w", encoding="utf-8") as f:
            json.dump(daily_tenders, f, ensure_ascii=False, indent=2)
            
        print(f"💾 今日 {len(daily_tenders)} 筆勞務標案已成功存檔至 {raw_csv_filename} 與 {raw_json_filename}！\n")
    else:
        print("💡 未抓取到任何標案資料。")
