/************************************************************
 * KBH BILLDESK GOOGLE SHEET API
 * Complete bridge for the Python BillDesk agent
 ************************************************************/

const SPREADSHEET_ID = "1nrtyu-drp9T9Lsgr0IB7eYpe7nurW42XMGU2iarpk_o";
const TOKEN = "KBH_BILLDESK_2026";

/*
 * GET endpoints:
 *   ?action=months
 *   ?action=students&month=SEPTEMBER%202026&token=...
 *   ?action=ping
 */
function doGet(e) {
  try {
    const action = e && e.parameter ? String(e.parameter.action || "ping") : "ping";

    if (action === "months") {
      const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
      const sheets = ss.getSheets();
      const months = sheets.map(s => s.getName()).filter(Boolean);
      return json({
        ok: true,
        status: "ok",
        spreadsheetId: SPREADSHEET_ID,
        spreadsheetName: ss.getName(),
        sheetCount: sheets.length,
        months: months
      });
    }

    if (action === "diagnostic") {
      const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
      const sheets = ss.getSheets();
      return json({
        ok: true,
        status: "ok",
        spreadsheetId: SPREADSHEET_ID,
        spreadsheetName: ss.getName(),
        sheetCount: sheets.length,
        sheets: sheets.map(s => ({name:s.getName(), hidden:s.isSheetHidden()}))
      });
    }

    if (action === "students") {
      checkToken(e.parameter.token);
      const month = String(e.parameter.month || "").trim();
      if (!month) return json({ok:false, error:"Month is required"});
      return json({ok:true, students:getStudents(month), summary:getMonthSummary(month)});
    }

    return json({
      ok: true,
      status: "ok",
      message: "KBH BillDesk Google Sheet API is running",
      timestamp: new Date().toISOString()
    });

  } catch (err) {
    return json({ok:false, status:"error", error:String(err.message || err)});
  }
}

/*
 * POST action=update:
 * {
 *   token, action:"update", month, rollNo/admission_no,
 *   status, paymentDate, amount, paymentRef, transactionId, error, retryCount
 * }
 */
function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return json({ok:false, error:"No POST data received"});
    }

    const data = JSON.parse(e.postData.contents);
    checkToken(data.token);

    const action = String(data.action || "update");

    if (action === "test") {
      return json({ok:true, status:"ok", message:"POST API is working", received:data});
    }

    if (action !== "update") {
      return json({ok:false, error:"Unknown POST action: " + action});
    }

    const month = String(data.month || "").trim();
    const roll = String(
      data.rollNo || data.roll_no || data.admissionNo || data.admission_no || ""
    ).trim();

    if (!month) return json({ok:false, error:"Month is required"});
    if (!roll) return json({ok:false, error:"Roll No / Admission No is required"});

    const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(month);
    if (!sheet) return json({ok:false, error:"Sheet not found: " + month});

    const rowInfo = findStudentRow(sheet, roll);
    if (!rowInfo) return json({ok:false, error:"Student not found: " + roll});

    const headers = getHeaders(sheet);
    const cols = ensureOutputColumns(sheet, headers);

    setCell(sheet, rowInfo.row, cols.status, data.status || data.paymentStatus || "");
    setCell(sheet, rowInfo.row, cols.date, data.paymentDate || "");
    setCell(sheet, rowInfo.row, cols.amount, data.amount ?? "");
    setCell(sheet, rowInfo.row, cols.ref, data.paymentRef || data.paymentRefNo || "");
    setCell(sheet, rowInfo.row, cols.transaction, data.transactionId || data.transaction_id || "");
    setCell(sheet, rowInfo.row, cols.checked, new Date());
    setCell(sheet, rowInfo.row, cols.retry, data.retryCount ?? data.retry_count ?? 0);
    setCell(sheet, rowInfo.row, cols.error, data.error || "");

    SpreadsheetApp.flush();

    return json({
      ok:true,
      status:"success",
      message:"Student updated",
      month:month,
      rollNo:roll,
      row:rowInfo.row
    });

  } catch (err) {
    return json({ok:false, status:"error", error:String(err.message || err)});
  }
}

function checkToken(token) {
  if (String(token || "") !== TOKEN) {
    throw new Error("Invalid token");
  }
}

function getStudents(month) {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(month);
  if (!sheet) throw new Error("Sheet not found: " + month);

  const data = sheet.getDataRange().getDisplayValues();
  if (data.length < 2) return [];

  const headers = data[0].map(h => String(h).trim().toLowerCase());

  let rollIndex = findHeader(headers, [
    "roll no", "roll number", "rollno",
    "admission no", "admission number", "admissionno"
  ]);

  if (rollIndex < 0) throw new Error("Roll No / Admission No column not found");

  const statusIndex = findHeader(headers, [
    "paid", "payment status", "status"
  ]);
  const dateIndex = findHeader(headers, [
    "date", "payment date"
  ]);
  const amountIndex = findHeader(headers, [
    "amount", "paid amount"
  ]);
  const refIndex = findHeader(headers, [
    "reciept id", "receipt id", "payment ref no", "payment ref"
  ]);
  const transactionIndex = findHeader(headers, [
    "transaction id", "transaction"
  ]);
  const retryIndex = findHeader(headers, [
    "retry count"
  ]);
  const errorIndex = findHeader(headers, [
    "last error", "error"
  ]);

  const students = [];

  for (let r = 1; r < data.length; r++) {
    const roll = String(data[r][rollIndex] || "").trim();
    if (!roll) continue;

    students.push({
      row: r + 1,
      rollNo: roll,
      status: statusIndex >= 0 ? String(data[r][statusIndex] || "").trim() : "",
      paymentDate: dateIndex >= 0 ? String(data[r][dateIndex] || "").trim() : "",
      amount: amountIndex >= 0 ? String(data[r][amountIndex] || "").trim() : "",
      paymentRef: refIndex >= 0 ? String(data[r][refIndex] || "").trim() : "",
      transactionId: transactionIndex >= 0 ? String(data[r][transactionIndex] || "").trim() : "",
      retryCount: retryIndex >= 0 ? String(data[r][retryIndex] || "").trim() : "0",
      error: errorIndex >= 0 ? String(data[r][errorIndex] || "").trim() : ""
    });
  }

  return students;
}


function getMonthSummary(month) {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(month);
  if (!sheet) throw new Error("Sheet not found: " + month);

  const data = sheet.getDataRange().getDisplayValues();
  if (data.length < 2) {
    return {totalStudents:0, paidStudents:0, pendingStudents:0, errorStudents:0,
            paidAmount:0, pendingAmount:0, totalAmount:0, feeSource:"AMOUNT"};
  }

  const headers = data[0].map(h => String(h).trim().toLowerCase());
  const rollIndex = findHeader(headers, ["roll no", "roll number", "rollno", "admission no", "admission number", "admissionno"]);
  const statusIndex = findHeader(headers, ["paid", "payment status", "status"]);
  const amountIndex = findHeader(headers, ["amount", "paid amount"]);

  if (rollIndex < 0) throw new Error("Roll No / Admission No column not found");

  let totalStudents = 0;
  let paidStudents = 0;
  let pendingStudents = 0;
  let errorStudents = 0;
  let paidAmount = 0;
  let pendingAmount = 0;
  let totalAmount = 0;

  for (let r = 1; r < data.length; r++) {
    const roll = String(data[r][rollIndex] || "").trim();
    if (!roll) continue;

    totalStudents++;
    const status = statusIndex >= 0 ? String(data[r][statusIndex] || "").trim().toUpperCase() : "";
    const amount = amountIndex >= 0
      ? Number(String(data[r][amountIndex] || "").replace(/[^0-9.\-]/g, "")) || 0
      : 0;

    // In this sheet, column H = AMOUNT is the amount due for NOT PAID rows
    // and the amount actually paid for PAID rows. Therefore all three dashboard
    // totals must be calculated directly from column H.
    totalAmount += amount;

    if (status === "PAID") {
      paidStudents++;
      paidAmount += amount;
    } else {
      pendingStudents++;
      pendingAmount += amount;
      if (status === "ERROR") errorStudents++;
    }
  }

  return {
    totalStudents,
    paidStudents,
    pendingStudents,
    errorStudents,
    paidAmount,
    pendingAmount,
    totalAmount,
    feeSource: amountIndex >= 0 ? headers[amountIndex] : "AMOUNT"
  };
}

function findStudentRow(sheet, roll) {
  const data = sheet.getDataRange().getDisplayValues();
  if (data.length < 2) return null;

  const headers = data[0].map(h => String(h).trim().toLowerCase());

  const rollIndex = findHeader(headers, [
    "roll no", "roll number", "rollno",
    "admission no", "admission number", "admissionno"
  ]);

  if (rollIndex < 0) throw new Error("Roll No / Admission No column not found");

  for (let r = 1; r < data.length; r++) {
    if (
      String(data[r][rollIndex] || "").trim().toUpperCase() ===
      String(roll).trim().toUpperCase()
    ) {
      return {row:r + 1};
    }
  }

  return null;
}

function getHeaders(sheet) {
  const last = Math.max(sheet.getLastColumn(), 1);
  return sheet.getRange(1, 1, 1, last)
    .getDisplayValues()[0]
    .map(h => String(h).trim());
}

function ensureOutputColumns(sheet, headers) {
  const findOrCreate = function(names, fallbackName) {
    const lower = headers.map(h => h.toLowerCase());
    for (const n of names) {
      const i = lower.indexOf(n.toLowerCase());
      if (i >= 0) return i + 1;
    }
    const col = sheet.getLastColumn() + 1;
    sheet.getRange(1, col).setValue(fallbackName);
    headers.push(fallbackName);
    return col;
  };

  return {
    status: findOrCreate(["PAID", "Payment Status", "Status"], "PAID"),
    date: findOrCreate(["DATE", "Payment Date"], "DATE"),
    amount: findOrCreate(["AMOUNT", "Paid Amount"], "AMOUNT"),
    ref: findOrCreate(["RECIEPT ID", "RECEIPT ID", "Payment Ref No", "Payment Ref"], "RECIEPT ID"),
    transaction: findOrCreate(["Transaction ID", "Transaction Id"], "Transaction ID"),
    checked: findOrCreate(["Last Checked"], "Last Checked"),
    retry: findOrCreate(["Retry Count"], "Retry Count"),
    error: findOrCreate(["Last Error", "Error"], "Last Error")
  };
}

function setCell(sheet, row, col, value) {
  if (col) sheet.getRange(row, col).setValue(value);
}

function findHeader(headers, names) {
  for (const name of names) {
    const i = headers.indexOf(name.toLowerCase());
    if (i >= 0) return i;
  }
  return -1;
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
