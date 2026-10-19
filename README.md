# RSS Feeds

A beat writer's feed, read against the schedule. Stories are not a flat list:
each one sits in the gap between the two games it was filed between, so the
rhythm of the coverage shows — the recap that lands the same night, the column
the next morning, the contract news that breaks on an off day.

Live: https://kyeill.github.io/rss-feeds/ · repo: kyeill/rss-feeds

First feed: **Detroit Red Wings — The Athletic**, through
[siftrss](https://siftrss.com/f/Jz69b6rknd9), matched against the NHL's public
schedule for Detroit.

## The pieces

| file | what it does |
| --- | --- |
| `config.json` | the read-list address, and the feeds: tab name, source, NHL club, local TV channel, feed URL |
| `build.py` | reads each feed and that club's season, writes one page with a tab per feed |
| `template.html` | the whole page — CSS and the script that lays out the timeline |
| `docs/index.html` | the built page, committed, served by Pages from `main` |
| `apps-script/` | the read-list web app the page syncs with (see below) |

```bash
python build.py
```

No dependencies; standard library only. GitHub Actions runs the same command
every three hours and commits `docs/` when the feed has moved.

## The page

A tab per feed across the top — **Red Wings (52)**, the number being unread
stories; the count disappears at zero. The selected tab is the `#slug` in the
address, so a tab can be bookmarked. Under it: record, points, the last-eight
strip, the next game (opponent, time, arena, one TV network), then the timeline,
newest first. There are no filters: every story and every game, preseason
included.

Kyle asked on 2026-10-18 for: no timing tags on stories, no filter row, no
tagline, no trip or "then" commentary on Up next, `G#` game numbers, small
`vs`/`at`, overtime and shootout losses grey like any loss, and one TV network
per game. The Athletic's own teaser stays as the summary (he chose that over
generated summaries, which would need the paywalled article text).

## How a story finds its place

Every story sits under the last finished game before it was filed, with a small
line saying how long after ("12h after vs SJS 4–3", "3 days after at MTL").
Gap labels between games count the stories filed in each break. Games carry the
record as it stood after them, so the standings move down the page with the
stories. Preseason games show as `PS` and change no record.

**TV:** a US national broadcast if the game has one (ESPN, ESPN+, TNT, ABC…),
otherwise the feed's `localTv` (Detroit SportsNet). NHL Network doesn't count
as national: its games stay on the local channel too. A game the API lists no
broadcast for at all shows none.

## Read and unread

Opening a story marks it read, and the mark follows Kyle to every device. An
unread story's date is red; once read, the date and headline turn grey, and the
tab's count drops. (An "Unread only" filter and a "Mark all read" button existed
briefly and went with the filter row.)

The page is static, so the list lives in an Apps Script web app,
"RSS Feeds Read Sync", in Kyle's Google account (`apps-script/Code.js`, one
Script Property per story id). Its `/exec` address is `sync` in `config.json`;
`build.py` writes it into the page. Each browser also keeps a copy in
`localStorage`, so marks show at once and survive a dropped connection; any
mark the server hasn't acknowledged is retried on the next load. The page
re-reads the list whenever it comes back to the foreground. The footer says
whether the last sync worked.

Story ids are The Athletic's article number from the link (`/athletic/7699924/`),
or a 12-character hash for any other source.

Deploying a change to the script — clasp, from Claude's shell, never by hand:

```bash
export PATH="/c/Program Files/nodejs:/c/Users/kyleh/AppData/Roaming/npm:$PATH"
clasp push -f
clasp create-deployment -i AKfycbw8vFkELzj4_cTKh7vrQ55az3JtItkFBx_6PoCL20EJ5HnHCfomt4u75FrOKVrSgxh_2g -d "what changed"
```

`create-deployment -i` makes a new version and repoints the existing deployment,
so the address in `config.json` never changes. `.clasp.json` (the script id) is
gitignored and lives only in the local folder.

## Traps already paid for

- **`clasp create-script` overwrites `appsscript.json`** with a bare default
  that has no `webapp` block. Pushed like that, the web app would refuse every
  call from the page. The manifest must keep `executeAs: USER_DEPLOYING` and
  `access: ANYONE_ANONYMOUS`.
- **The read list's address is public** — it is in the page. Anyone who reads
  the source could see or change which stories are marked read. Accepted: it
  holds nothing but article numbers. The script takes only short id strings,
  at most 1000 per call, and drops marks older than 400 days.
- **Clearing a mark on the server alone doesn't stick.** A browser that still
  has it locally will resend it. To unmark for good, clear that browser's
  site data too.

- **Anchor on puck drop, not the calendar date.** A 7pm game and an 8pm story
  are the same night; by date alone a story filed at 00:30 would be stranded a
  day away from the game it is about.
- **Times are Detroit's, not the browser's.** The feed publishes in GMT and
  the schedule in UTC; both are formatted through `America/Detroit` so a
  6am column does not read as 11am.
- **The gap label counts the stories in it**, including "nothing filed" —
  silence between games is information too.
- **Nothing here knows what a story is about.** The tags are timing, not
  subject: a trade-request story filed an hour after a loss is tagged *Same
  night* like any recap.
- **Every link is paywalled.** It is an Athletic feed; the page shows the
  headline and dek the feed carries and links out.
