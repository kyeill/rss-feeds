/**
 * RSS Feeds Refresh -- starts the rss-feeds build once an hour.
 *
 * The build is meant to run every three hours on GitHub's own schedule, but
 * GitHub has delivered this account's scheduled runs four to five hours late,
 * or not at all, since September 2026. A build started through GitHub's API
 * runs at once, so this time-driven trigger starts it instead. The workflow's
 * cron stays as a backup.
 *
 * Needs one Script Property, GITHUB_TOKEN: a fine-grained GitHub token for
 * kyeill/rss-feeds only, with Actions read and write and nothing else. Kyle
 * pastes it in Project Settings himself; it is never in this file or the repo.
 *
 * Run setup() once from the editor: it asks for permission, installs the
 * hourly trigger (replacing any earlier one) and starts one build to prove it.
 * A failed run throws, and Apps Script emails Kyle about it -- an expired
 * token shows up that way.
 *
 * Deployed with clasp from this folder, giving -P the FULL Windows path
 * (clasp 3 calls a relative "." a path escape): clasp -P "$(cygpath -w "$PWD")" push -f
 */

var REPO = "kyeill/rss-feeds";
var WORKFLOW = "build.yml";

function refresh() {
  var token = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  if (!token) throw new Error("No GITHUB_TOKEN in Project Settings > Script properties");
  var res = UrlFetchApp.fetch(
    "https://api.github.com/repos/" + REPO + "/actions/workflows/" + WORKFLOW + "/dispatches", {
      method: "post",
      contentType: "application/json",
      headers: {
        Authorization: "Bearer " + token,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
      },
      payload: JSON.stringify({ ref: "main" }),
      muteHttpExceptions: true
    });
  if (res.getResponseCode() !== 204) {
    throw new Error("GitHub refused the build (" + res.getResponseCode() + "): " +
                    res.getContentText().slice(0, 300));
  }
}

function setup() {
  // Ask for every permission up front: Apps Script otherwise only asks for
  // what a run happens to touch, and a trigger can't ask at all.
  ScriptApp.requireAllScopes(ScriptApp.AuthMode.FULL);
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === "refresh") ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger("refresh").timeBased().everyHours(1).create();
  refresh();
  Logger.log("Hourly refresh installed, and a build was started just now.");
}
