/**
 * 帆船標案前台的後端（Google Apps Script 網頁應用程式）
 *
 * 流程：前台用 Google 登入 → 把登入憑證送來 → 這裡跟 Google 確認身分
 *       → 帳號在允許名單上，才讀試算表、把資料回傳給前台。
 * 這樣試算表就能關掉「知道連結的人都能檢視」，資料不再公開。
 *
 * 允許名單：
 *   - 部署這支程式的人（試算表擁有者）永遠可以看。
 *   - 要多開放給別人，到「專案設定 → 指令碼屬性」新增
 *     ALLOWED_EMAILS，值填帳號，多個用逗號隔開。
 *
 * 部署方式：部署 → 新增部署 → 網頁應用程式
 *   執行身分：我；誰可以存取：所有人
 */

// 試算表與分頁
const SPREADSHEET_ID = '1Hc2KqH0ZWT1Ty-5RBa4zdsx-8RLrHG-tNE5qJHuaQ6U';
const CONFIG_SHEET = '系統設定';
const TENDER_SHEET = '每日勞務標案';

// Google 登入用的 OAuth 用戶端 ID（跟邊坡圖資共用，公開沒關係）
const CLIENT_ID = '265991764431-7mv80vl7iighqahnbd1nihgpff50odf6.apps.googleusercontent.com';

// 前台不需要的長欄位（H 欄「廠商資格與說明」），不回傳
const SKIP_COLUMN = 'H';


/** 直接用瀏覽器打開網址時，回一句話確認服務有在跑 */
function doGet() {
  return toJson({ ok: true, message: '帆船標案前台後端運作中' });
}

/** 前台送資料請求進來 */
function doPost(e) {
  try {
    const request = JSON.parse(e.postData.contents);
    const email = checkLogin(request.token);

    if (!isAllowed(email)) {
      return toJson({ error: 'NO_ACCESS', message: email + ' 沒有使用權限，請聯絡管理員。' });
    }

    return toJson({
      email: email,
      config: readConfig(),
      tenders: readTenders()
    });
  } catch (err) {
    return toJson({ error: err.code || 'ERROR', message: String(err.message || err) });
  }
}


// ───────── 登入與權限 ─────────

/** 跟 Google 確認登入憑證是真的，回傳登入者的 email */
function checkLogin(token) {
  if (!token) throwError('TOKEN', '請先登入');

  // 同一張憑證在有效期限內只查一次，加快速度
  const cache = CacheService.getScriptCache();
  const cacheKey = 'login_' + Utilities.base64EncodeWebSafe(
    Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, token));
  const cachedEmail = cache.get(cacheKey);
  if (cachedEmail) return cachedEmail;

  const response = UrlFetchApp.fetch(
    'https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(token),
    { muteHttpExceptions: true });
  if (response.getResponseCode() !== 200) throwError('TOKEN', '登入已過期，請重新登入');

  const info = JSON.parse(response.getContentText());
  const fromGoogle = info.iss === 'accounts.google.com' || info.iss === 'https://accounts.google.com';
  const forThisSite = info.aud === CLIENT_ID;
  const emailVerified = String(info.email_verified) === 'true';
  const notExpired = Number(info.exp) * 1000 > Date.now();
  if (!fromGoogle || !forThisSite || !emailVerified || !notExpired) {
    throwError('TOKEN', '登入憑證無效，請重新登入');
  }

  const email = String(info.email).toLowerCase();
  const secondsLeft = Number(info.exp) - Math.floor(Date.now() / 1000) - 30;
  cache.put(cacheKey, email, Math.max(1, Math.min(1800, secondsLeft)));
  return email;
}

/** 這個帳號可不可以看資料 */
function isAllowed(email) {
  const owner = String(Session.getEffectiveUser().getEmail()).toLowerCase();
  if (email === owner) return true;

  const extra = PropertiesService.getScriptProperties().getProperty('ALLOWED_EMAILS') || '';
  return extra.split(',')
    .map(item => item.trim().toLowerCase())
    .filter(item => item)
    .includes(email);
}


// ───────── 讀試算表 ─────────
// 回傳格式刻意做成跟 Google 試算表 gviz 一樣，前台原本的顯示程式不用改。

/** 系統設定：B1～B4（標題、最低預算、最高預算、擅長條件） */
function readConfig() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(CONFIG_SHEET);
  const values = sheet.getRange('B1:B4').getDisplayValues();
  return {
    table: {
      rows: values.map(row => ({ c: [{ v: row[0] }] }))
    }
  };
}

/** 每日勞務標案：第一列是欄名，其餘是資料；略過 H 欄 */
function readTenders() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(TENDER_SHEET);
  const values = sheet.getDataRange().getDisplayValues();
  if (values.length === 0) return { table: { cols: [], rows: [] } };

  const skipIndex = SKIP_COLUMN.charCodeAt(0) - 'A'.charCodeAt(0);
  const keep = (_, index) => index !== skipIndex;

  const header = values[0].filter(keep);
  const dataRows = values.slice(1)
    .filter(row => row.some(cell => cell !== ''))   // 跳過整列空白
    .map(row => row.filter(keep));

  return {
    table: {
      cols: header.map(label => ({ label: label })),
      rows: dataRows.map(row => ({ c: row.map(cell => ({ v: cell })) }))
    }
  };
}


// ───────── 小工具 ─────────

function toJson(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function throwError(code, message) {
  const err = new Error(message);
  err.code = code;
  throw err;
}

// 部署紀錄：2026/11/17 第 1 版
// 網址 https://script.google.com/macros/s/AKfycbzRH784INxfhqynOIy4LIhB_b6qHfaFifbI8NRgIbrcriBlKsVu4CpOMjJ9uzUtqg48IQ/exec
// 改程式後要「部署 → 管理部署作業 → 編輯 → 版本選新版本」，網址才會維持不變。
