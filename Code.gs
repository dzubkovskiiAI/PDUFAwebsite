/**
 * PDUFA tracker -> Google Sheets, as a container-bound Apps Script.
 *
 * Laptop route (SOURCE = 'drive'): the pipeline copies events.json into a Google Drive folder
 * (Drive for Desktop syncs it), and this script reads that file. Nothing is made public.
 * Web route (SOURCE = 'url'): the script downloads events.json from DATA_URL instead.
 *
 * Setup
 *  1. Open a Google Sheet. Extensions > Apps Script. Paste this file.
 *  2. Pick SOURCE below. For 'url', also set DATA_URL.
 *  3. Run refreshPdufa once and approve the permissions. A "PDUFA" tab appears.
 *  4. Run installDailyTrigger once so the tab refreshes every morning.
 *
 * The "Indication" column uses the same nine names as the trials app, so other scripts can
 * look rows up with getPdufaForIndication("Melanoma").
 */
const SOURCE = 'drive';                       // 'drive' or 'url'
const DRIVE_FILE_NAME = 'events.json';        // file the pipeline copies into your Drive folder
const DATA_URL = 'https://YOUR-USER.github.io/YOUR-REPO/data/events.json';   // only for SOURCE = 'url'
const SHEET_NAME = 'PDUFA';
const HEADER = ['Indication', 'Drug', 'Company', 'Detail', 'Goal date', 'Precision', 'Status',
                'Trust', 'Source', 'Source type', 'Last checked', 'ID'];
const TEXT_COLUMNS = [5, 11];   // keep "2027-02" as text instead of letting Sheets turn it into a date

function onOpen() {
  SpreadsheetApp.getUi().createMenu('PDUFA').addItem('Refresh now', 'refreshPdufa').addToUi();
}

function readFromUrl_() {
  const res = UrlFetchApp.fetch(DATA_URL, {muteHttpExceptions: true});
  const code = res.getResponseCode();
  if (code !== 200) throw new Error('Could not fetch ' + DATA_URL + ' (HTTP ' + code + ')');
  return JSON.parse(res.getContentText());
}

function readFromDrive_() {
  const files = DriveApp.getFilesByName(DRIVE_FILE_NAME);
  let newest = null;
  while (files.hasNext()) {
    const f = files.next();
    if (!newest || f.getLastUpdated() > newest.getLastUpdated()) newest = f;
  }
  if (!newest) {
    throw new Error('Could not find ' + DRIVE_FILE_NAME + ' in Google Drive. ' +
                    'Is Drive for Desktop syncing the export folder?');
  }
  return JSON.parse(newest.getBlob().getDataAsString());
}

function precisionOf_(d) {
  return /^\d{4}-\d{2}-\d{2}$/.test(d) ? 'day' : /^\d{4}-\d{2}$/.test(d) ? 'month' : 'quarter';
}

function refreshPdufa() {
  const payload = SOURCE === 'url' ? readFromUrl_() : readFromDrive_();
  const rows = payload.events.map(function (e) {
    const primary = e.sources.filter(function (s) { return s.type !== 'secondary'; });
    const src = primary[0] || e.sources[0] || {};
    return [e.condition, e.drug, e.company, e.indication, e.date, precisionOf_(e.date), e.status,
            e.review, src.url || '', src.type || '', (e.last_checked || '').slice(0, 10), e.id];
  });
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME) ||
                SpreadsheetApp.getActive().insertSheet(SHEET_NAME);
  sheet.clearContents();
  sheet.getRange(1, 1, 1, HEADER.length).setValues([HEADER]).setFontWeight('bold');
  TEXT_COLUMNS.forEach(function (c) { sheet.getRange(2, c, Math.max(rows.length, 1), 1).setNumberFormat('@'); });
  if (rows.length) sheet.getRange(2, 1, rows.length, HEADER.length).setValues(rows);
  sheet.setFrozenRows(1);
  PropertiesService.getScriptProperties().setProperty('lastRefresh', payload.meta.generated_at || '');
}

/** For other scripts: all PDUFA rows for one indication, e.g. getPdufaForIndication('Melanoma'). */
function getPdufaForIndication(label) {
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
  if (!sheet || sheet.getLastRow() < 2) return [];
  return sheet.getRange(2, 1, sheet.getLastRow() - 1, HEADER.length).getValues()
    .filter(function (r) { return r[0] === label; })
    .map(function (r) {
      return {drug: r[1], company: r[2], detail: r[3], goalDate: r[4], precision: r[5],
              status: r[6], trust: r[7], source: r[8]};
    });
}

/**
 * One summary row per indication, shaped for an explorer list: counts, next decision, and events.
 * Works with SOURCE = 'url' (reads by_indication.json beside events.json). Cached for six hours.
 * Example: getPdufaSummary('Melanoma') -> {label, upcoming, next_decision: {drug, date, ...}, events: [...]}
 */
function getPdufaSummary(label) {
  const url = DATA_URL.replace('events.json', 'by_indication.json');
  const cache = CacheService.getScriptCache();
  let text = cache.get('pdufaSummary');
  if (!text) {
    const res = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
    if (res.getResponseCode() !== 200) throw new Error('Could not fetch ' + url + ' (HTTP ' + res.getResponseCode() + ')');
    text = res.getContentText();
    try { cache.put('pdufaSummary', text, 21600); } catch (e) { /* too large to cache: fine */ }
  }
  const feed = JSON.parse(text);
  if (!label) return feed;
  return feed.indications.filter(function (r) { return r.label === label; })[0] || null;
}

function installDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'refreshPdufa') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('refreshPdufa').timeBased().everyDays(1).atHour(8).create();
}
