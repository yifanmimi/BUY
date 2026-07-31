import os
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Google Sheets 寫入邏輯
# ---------------------------------------------------------------------------
def write_to_google_sheet(data):
    """將標案資料直接寫入 Google 試算表"""
    if not data:
        print("⚠️ 無資料可寫入試算表。")
        return

    # 從環境變數讀取憑證與試算表 ID
    sa_key_json = os.environ.get("GCP_SA_KEY")
    spreadsheet_key = os.environ.get("SPREADSHEET_KEY")

    if not sa_key_json or not spreadsheet_key:
        raise ValueError("❌ 缺少 GCP_SA_KEY 或 SPREADSHEET_KEY 環境變數設定！")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds_dict = json.loads(sa_key_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    # 開啟試算表
    spreadsheet = client.open_by_key(spreadsheet_key)
    
    # 取得或建立「每日勞務標案」分頁
    try:
        sheet = spreadsheet.worksheet("每日勞務標案")
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="每日勞務標案", rows="1000", cols="10")

    # 清空舊資料並寫入標頭
    sheet.clear()
    headers = ["抓取日期時間", "招標機關", "標案名稱", "詳細連結"]
    sheet.append_row(headers)

    # 準備寫入的列資料
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_to_insert = []
    for item in data:
        rows_to_insert.append([
            now_str,
            item["org"],
            item["title"],
            item["link"]
        ])

    # 批次寫入試算表
    sheet.append_rows(rows_to_insert)
    print(f"📊 已成功將 {len(rows_to_insert)} 筆標案資料寫入 Google 試算表！")


# ---------------------------------------------------------------------------
# Playwright 爬蟲邏輯
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
            await page.goto("https://web.pcc.gov.tw/prkms/tender/common/basic/readTenderBasic", wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)

            # 1. 勾選「當日」與「勞務類」
            today_label = page.locator("label").filter(has_text="當日").first
            await today_label.click(force=True)

            service_label = page.locator("label[for='RadProctrgCate3'], #RadProctrgCate3").first
            await service_label.click(force=True)

            # 2. 送出搜尋
            print("🚀 送出查詢，抓取今日全量勞務案...")
            search_button = page.locator("input[value='搜尋'], #btnSearch, a:has-text('搜尋')").first
            
            if await search_button.is_visible():
                await search_button.click(force=True)
            else:
                await page.evaluate("typeof query === 'function' ? query() : document.forms[0].submit();")

            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)

            # 3. 逐頁解析
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

                # 下一頁
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
# 主程式
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    daily_tenders = asyncio.run(fetch_all_daily_services())
    
    if daily_tenders:
        write_to_google_sheet(daily_tenders)
    else:
        print("💡 未抓取到任何標案資料，取消寫入。")
