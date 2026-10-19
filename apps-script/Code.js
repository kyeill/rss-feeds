/**
 * RSS Feeds Read Sync -- which stories Kyle has opened, shared by every device.
 *
 * The page is static (GitHub Pages), so it has nowhere of its own to keep this.
 * One Script Property per story: key "r:<story id>", value the time it was
 * read. One property per story rather than one list, because a single property
 * stops at 9 KB and a season of stories outgrows that.
 *
 *   GET  ?op=get                 -> {ok, read:[ids]}
 *   POST {"read":[ids]}          -> marks them read, answers like GET
 *   POST {"unread":[ids]}        -> clears them (the page never sends this;
 *                                   it is for tests and hand repairs)
 *
 * The page POSTs as text/plain so the browser sends it without a CORS
 * preflight, which Apps Script cannot answer.
 *
 * Deployed with clasp (see the README); runs as Kyle, callable by anyone.
 */

var ID = /^[A-Za-z0-9_-]{1,40}$/;
var KEEP_DAYS = 400;            // a season and change; older marks are dropped

function doGet(e) {
  return reply_(readIds_());
}

function doPost(e) {
  var body;
  try {
    body = JSON.parse((e.postData && e.postData.contents) || "{}");
  } catch (err) {
    return json_({ ok: false, error: "body is not JSON" });
  }
  var valid = function (list) {
    return (list || []).filter(function (id) { return ID.test(String(id)); }).slice(0, 1000);
  };
  var ids = valid(body.read), gone = valid(body.unread);

  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var props = PropertiesService.getScriptProperties();
    var now = Date.now(), add = {};
    ids.forEach(function (id) { add["r:" + id] = String(now); });
    if (ids.length) props.setProperties(add, false);
    gone.forEach(function (id) { props.deleteProperty("r:" + id); });
    prune_(props, now);
  } finally {
    lock.releaseLock();
  }
  return reply_(readIds_());
}

function readIds_() {
  return Object.keys(PropertiesService.getScriptProperties().getProperties())
    .filter(function (k) { return k.indexOf("r:") === 0; })
    .map(function (k) { return k.slice(2); });
}

function prune_(props, now) {
  var all = props.getProperties(), cutoff = now - KEEP_DAYS * 864e5;
  Object.keys(all).forEach(function (k) {
    if (k.indexOf("r:") === 0 && Number(all[k]) < cutoff) props.deleteProperty(k);
  });
}

function reply_(ids) {
  return json_({ ok: true, read: ids });
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
