import os
import json
import re
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# ---------------------------------------------------------------------------
# 1. 讀取 Google 試算表設定檔
# ---------------------------------------------------------------------------
def get_system_settings(spreadsheet):
    """讀取『系統設定』分頁中的條件參數"""
    try:
        setting_sheet = spreadsheet.worksheet("系統設定")
        min_budget_str = str(setting_sheet.acell("B2").value or "0")
        max_budget_str = str(setting_sheet.acell("B3").value or "0")
        ai_prompt_condition = str(setting_sheet.acell("B4").value or "")

        # 清除金額字串中的非數字字符 (如 NT$, 逗號等)
        min_budget = int(re.sub(r"[^\d]", "", min_budget_str)) if re.sub(r"[^\d]", "", min_budget_str) else 0
        max_budget = int(re.sub(r"[^\d]", "", max_budget_str)) if re.sub(r"[^\d]", "", max_budget_str) else 0

        print(f"⚙️ 系統設定讀取成功：")
        print(f"   ├─ 最低預算：{min_budget:,} 元")
        print(f"   ├─ 最高預算：{max_budget:,} 元 (0表示無上限)")
        print(f"   └─ AI 擅長條件：{ai_prompt_condition}")

        return min_budget, max_budget, ai_prompt_condition
    except Exception as e:
        print(f"⚠️ 讀取『系統設定』分頁失敗，使用預設值: {e}")
        return 0, 0, ""

# ---------------------------------------------------------------------------
# 2. Gemini AI 評分邏輯 (批次處理超快版本)
# ---------------------------------------------------------------------------
def evaluate_tenders_with_ai(tenders, condition):
    """使用 Gemini API 批次進行標案名稱打分"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not condition:
        print("⚠️ 未設定 GEMINI_API_KEY 或 AI 條件為空，跳過 AI 打分。")
        for item in tenders:
            item["score"] = 0
            item["reason"] = "未執行 AI 評估"
            item["recommended"] = "否"
        return tenders

    genai.configure(api_key=api_key)
    # 使用最新強大的 Gemini 模型
    model = genai.GenerativeModel("gemini-3.5-flash")

    # 1. 篩選出符合預算、需要 AI 評分的標案
    valid_tenders = []
    for item in tenders:
        if not item.get("budget_pass", True):
            item["score"] = 0
            item["reason"] = "預算不符合設定範圍"
            item["recommended"] = "否"
        else:
            valid_tenders.append(item)

    if not valid_tenders:
        print("ℹ️ 無符合預算條件的標案需進行 AI 評估。")
        return tenders

    print(f"\n🤖 開始對 {len(valid_tenders)} 筆符合預算的標案進行批次 AI 打分...")

    # 2. 分批處理 (每批 20 筆)
    BATCH_SIZE = 20
    for i in range(0, len(valid_tenders), BATCH_SIZE):
        batch = valid_tenders[i:i + BATCH_SIZE]
        
        # 組裝批次 Prompt
        items_text = ""
        for idx, item in enumerate(batch):
            items_text += f"編號 {idx + 1}: {item['title']}\n"

        prompt = f"""
你是一個專業的政府標案篩選助手。
我們的公司擅長與關注的領域如下：
【{condition}】

請評估以下標案清單，依照與我們業務的相關度給予 0 到 100 的分數，並給出 15 字以內的簡短理由。

標案清單：
{items_text}

請嚴格按照以下 JSON 陣列格式回答，不要包含 Markdown 標籤或其他文字：
[
  {{"id": 1, "score": 85, "reason": "符合資安建置與防護需求"}},
  {{"id": 2, "score": 20, "reason": "業務不符合，屬於水利工程"}}
]
"""
        # 呼叫 API 並帶有容錯
        try:
            response = model.generate_content(prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            results = json.loads(clean_text)

            # 將結果匹配回原始標案資料
            res_dict = {res["id"]: res for res in results}
            for idx, item in enumerate(batch):
                res = res_dict.get(idx + 1, {})
                score = int(res.get("score", 0))
                reason = res.get("reason", "無評語")

                item["score"] = score
                item["reason"] = reason
                item["recommended"] = "★ 推薦 (≥70)" if score >= 70 else "否"

        except Exception as e:
            print(f"⚠️ 批次 {i // BATCH_SIZE + 1} 評估失敗: {e}")
            for item in batch:
                item["score"] = 0
                item["reason"] = "批次評估失敗"
                item["recommended"] = "否"

        # 批次之間微幅停頓 1 秒即可
        import time
        time.sleep(1)

    return tenders

# ---------------------------------------------------------------------------
# 3. Google Sheets 寫入邏輯
# ---------------------------------------------------------------------------
def write_to_google_sheet(data):
    if not data:
        print("⚠️ 無資料可寫入試算表。")
        return

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
    spreadsheet = client.open_by_key(spreadsheet_key)

    # 1. 讀取設定
    min_b, max_b, ai_cond = get_system_settings(spreadsheet)

    # 2. 金額初步過濾 (標註 budget_pass)
    for item in data:
        budget = item.get("budget", 0)
        # 如果有設定金額且不在區間內
        if (min_b > 0 and budget < min_b) or (max_b > 0 and budget > max_b):
            item["budget_pass"] = False
        else:
            item["budget_pass"] = True

    # 3. AI 打分 (只有金額符合的才會打分)
    processed_data = evaluate_tenders_with_ai(data, ai_cond)

    # 4. 寫入「每日勞務標案」分頁
    try:
        sheet = spreadsheet.worksheet("每日勞務標案")
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="每日勞務標案", rows="1000", cols="10")

    sheet.clear()
    headers = ["抓取時間", "招標機關", "標案名稱", "預算金額", "AI 評分", "AI 評語", "是否推薦 (≥70)", "詳細連結"]
    sheet.append_row(headers)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_to_insert = []
    
    for item in processed_data:
        rows_to_insert.append([
            now_str,
            item["org"],
            item["title"],
            f"{item['budget']:,}" if item['budget'] > 0 else "未提供/另行公告",
            item.get("score", 0),
            item.get("reason", ""),
            item.get("recommended", "否"),
            item["link"]
        ])

    sheet.append_rows(rows_to_insert)
    print(f"\n📊 已成功將 {len(rows_to_insert)} 筆標案寫入 Google 試算表！")

# ---------------------------------------------------------------------------
# 4. Playwright 爬蟲邏輯 (含預算金額解析)
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

            # 勾選當日與勞務類
            await page.locator("label").filter(has_text="當日").first.click(force=True)
            await page.locator("label[for='RadProctrgCate3'], #RadProctrgCate3").first.click(force=True)

            # 送出搜尋
            search_button = page.locator("input[value='搜尋'], #btnSearch, a:has-text('搜尋')").first
            if await search_button.is_visible():
                await search_button.click(force=True)
            else:
                await page.evaluate("typeof query === 'function' ? query() : document.forms[0].submit();")

            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)

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
                                
                                # 嘗試解析預算金額欄位 (若列表中有)
                                raw_budget = 0
                                for col in cols:
                                    text = col.get_text(strip=True)
                                    if "$" in text or "元" in text or text.replace(",", "").isdigit():
                                        nums = re.findall(r"\d+", text.replace(",", ""))
                                        if nums and len(nums[0]) >= 5: # 抓取可能為金額的數字
                                            raw_budget = int(nums[0])
                                            break

                                if len(title) > 2 and title not in ["檢視", "詳細內容", "列印", "查詢", "按鈕", "下一頁", "上一頁"]:
                                    full_link = f"https://web.pcc.gov.tw{href}" if href.startswith("/") else href
                                    
                                    tenders.append({
                                        "org": org_name,
                                        "title": title,
                                        "budget": raw_budget,
                                        "link": full_link
                                    })
                                    page_count += 1
                                    break

                # 下一頁
                next_button = page.locator("a:has-text('下一頁'), input[value='下一頁']").first
                if await next_button.is_visible():
                    page_num += 1
                    await next_button.click()
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(2000)
                else:
                    break

            print(f"\n🎉 抓取完成！共 {len(tenders)} 筆標案！")
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
