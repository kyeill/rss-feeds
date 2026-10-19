# RSS Feeds

A beat writer's feed, read against the schedule. Stories are not a flat list:
each one sits in the gap between the two games it was filed between, so the
rhythm of the coverage shows — the recap that lands the same night, the column
the next morning, the contract news that breaks on an off day.

Live: https://kyeill.github.io/rss-feeds/ · repo: kyeill/rss-feeds

A **home page** lists every section with its unread count; tapping one opens
it, and each section page has a **‹ Home** button in place of the old tab row
(Kyle, 2026-10-19). Order: (Michigan, to come) **Tottenham, Tigers, Lions,
Pistons, Red Wings, Cavaliers, Soccer, Power Rankings**. The address is the
route: no `#` is home, `#slug` a section, so the phone's Back button returns
home and a section can be bookmarked; the Home button goes Back when the page
came from home, and otherwise replaces the address. Swiping still moves
between sections on a section page (not on home). The first five —
each The Athletic's own team feed (`nytimes.com/athletic/rss/<league>/<team>/`,
URLs in `config.json`), filtered by the rules in Kyle's Sheet (below). Until
2026-10-19 the feeds came through siftrss, which did the filtering. The Red
Wings came first (2026-10-18); the other four were added the same night under
the same rules. Hockey uses the NHL's own API; baseball, football and
basketball use ESPN's.

## The pieces

| file | what it does |
| --- | --- |
| `config.json` | the read-list address, the rules Sheet, and the feeds: tab name, league (`nhl` `mlb` `nfl` `nba`), team abbreviation, local TV channel, feed URL |
| `build.py` | reads each feed and that club's season, writes one page with a tab per feed |
| `template.html` | the whole page — CSS and the script that lays out the timeline |
| `docs/index.html` | the built page, committed, served by Pages from `main` |
| `apps-script/` | the read-list web app the page syncs with (see below) |
| `refresh-script/` | a second Apps Script project, "RSS Feeds Refresh", that starts the build every hour (see below) |
| `icons.py` | draws the app icons into `docs/` (run by hand when the mark changes) |
| `docs/manifest.webmanifest`, `docs/sw.js` | make it installable on a phone; hand-written, not built |

```bash
python build.py
```

No dependencies; standard library only. GitHub Actions runs the same command
every three hours and commits `docs/` when the feed has moved.

## The page

A tab per team across the top — **Red Wings (52)**, the number being unread
stories; the count disappears at zero. Kyle plans a couple more teams in the
same format. The selected tab is the `#slug` in the
address, so a tab can be bookmarked. Under it, three figures in big text with
a small label: division place ("7th Place" / Atlantic Division), distance from
the playoff line ("2 Points Back" / of playoff spot, or "N Points Clear" / of
first team out), and playoff odds. Then the next game (opponent, time, arena, one TV network), then the timeline,
newest first. There are no filters: every story and every game, preseason
included.

Kyle asked on 2026-10-18 for: no timing tags on stories, no filter row, no
tagline, no trip or "then" commentary on Up next, game numbers in brackets (`[8]`; preseason blank — first `G8`, changed the same night), small
`vs`/`at`, overtime and shootout losses grey like any loss, and one TV network
per game. The Athletic's own teaser stays as the summary (he chose that over
generated summaries, which would need the paywalled article text).

## How a story finds its place

Every story sits under the last finished game before it was filed (a line
saying how long after was removed at Kyle's request, 2026-10-18). Nothing is written between games (gap labels like "2 days between games · 3 stories" were removed at his request). Stories filed before
the season's first game run on at the bottom with no heading (the "Offseason
into camp" chapter was removed at Kyle's request, as were the footer's source
credits). Games carry the
record as it stood after them, so the standings move down the page with the
stories. Preseason games carry no number and change no record.

**Playoff line:** each conference sends the top three of each division plus
two wild cards. A team outside is as far back as the NEARER of its division's
third place and the second wild card; a team inside is as far clear as it is
above the conference's first team out. From the NHL's `standings/now`.

**Playoff odds** come from Hockey-Reference's playoff probabilities page
(`/friv/playoff_prob.fcgi`; the old `.cgi` address redirects). MoneyPuck asks
not to be scraped, so it stays out. The page is fetched at most every 12 hours
and kept in `cache/nhl-odds.json`, which CI commits. Hockey-Reference only
starts a season once every team has played 10 games; until then it still shows
last season with blank odds, so a value is used only when the page's points
for the team match the NHL's. Until then the page shows "—" and "after 10
games".

**Each sport, under the same rules:**

| | stories kept from | gap unit | playoff line | odds |
| --- | --- | --- | --- | --- |
| NHL | July 1 | points | top 3 per division + 2 wild cards | Hockey-Reference |
| NBA | July 1 | games | top 6 seeds (7-10 are only the play-in) | ESPN power index |
| NFL | March 1 | games | 7 seeds; a division title is a ticket | ESPN power index |
| MLB | November 1 (prior year) | games | 6 seeds; a division title is a ticket | ESPN standings `playoffPercent` |

Records: hockey W-L-OT, football W-L (W-L-T once there's a tie), baseball and
basketball W-L. Results carry overtime ("W OT", "L SO", "L 2OT"); baseball's
extra innings are not shown. Preseason games have a blank number, postseason `PO`, neither
numbered nor counted. Postponed and cancelled games are dropped (the makeup is
its own event). The timeline starts at the game the oldest story follows: a
feed reaches back only ~100 stories, so the Tigers' tab begins in June rather
than with 70 empty gaps. ESPN's tables follow ESPN's idea of the current season
(the NBA's shows preseason records until opening night, MLB's the finished
season all winter), so a table whose games played disagree with the schedule's
shows "—" for place and gap; odds still show when they are this season's.
NFL times not yet set read "Time TBD".

The page opens on home unless the address names a section. On a phone, a quick sideways swipe below
the tabs moves to the next or previous team (a stroke must travel 60px, at
least twice as far sideways as down, within 0.7s — so scrolling never changes
team); the tab row keeps its own sideways scroll.

**Colours:** each tab wears its team's colour, Kyle's picks (2026-10-18): Tigers
orange, Lions blue, Pistons teal, Cavaliers gold, Red Wings red. They are CSS
tokens in `template.html` keyed on `data-team` (the slug), light and dark:
`--accent` fills (tab underline, game dots, win pills and bands, Up next rule),
`--accent-text` is the same hue dark enough to read as text (unread dates, win
game numbers — all at least 4.5:1), `--on-accent` is the text on a win pill
(dark on orange, teal and gold). A new team needs its own block or it falls
back to red.

**TV:** a US national broadcast if the game has one (ESPN, ESPN+, TNT, ABC…),
otherwise the feed's `localTv` (Detroit SportsNet). NHL Network doesn't count
as national: its games stay on the local channel too. A game the API lists no
broadcast for at all shows none. For ESPN sports the same idea: a national
listing (TV before streaming) unless it is MLB.TV, MLB Network, NBA TV or NBA
League Pass, then the team's own home/away listing (the Tigers' is
"Tigers.TV"), then `localTv`: **TV20 Detroit** for the Pistons and **DAZN** for
the Cavaliers, both new in 2026-27 and absent from ESPN's data. The Lions have
none — every NFL game has a network.

## Tottenham, Soccer and Power Rankings (added 2026-10-19)

**Tottenham** works like the other team tabs, from ESPN soccer: every
competition is asked separately (`SOCCER_COMPS` — Premier League, League Cup,
FA Cup, the three UEFA cups), each twice, because a team schedule gives played
games by default and fixtures only with `fixture=true`. A competition the
club isn't in answers empty, and the FA Cup answers 500 until the club's in
the draw — both are skipped. League games are numbered `[n]`; cup games carry
no number and name the competition in their meta line. Results are W / D / L
(ESPN's winner flag, so a penalty-shootout cup tie reads right), the record is
W-D-L. The standing reads ESPN's zone notes: in the relegation places it shows
points **from safety**, otherwise points back of (or clear of) the Champions
League places. No one publishes odds for a league table, so the third figure
is the W-D-L record. TV: the English channel (NBC, USA Network, Peacock,
Paramount+), never the Spanish one ESPN lists beside it.

**Soccer** and **Power Rankings** are story-only tabs (`kind: "stories"`): no
schedule, no table, no Up next. Each story carries its source label after the
time ("USMNT", "NFL"). Soccer reads the USMNT feed (`football/usmnt`) and Atlanta
United's (`football/atlunited` — Kyle supplied it; guessed slugs all 404).
Kyle's brief for it: USMNT match coverage and player roundups only, no
single-player deep dives or FIFA politics; Atlanta stories plus at most a
weekly MLS roundup, which is The Athletic's Sunday column "The Verdict". Power Rankings reads
the four Detroit team feeds and keeps only headlines with "power rankings":
the league feeds hold only a week or two of stories, but every ranking
mentions every team, so the team feeds carry each one for months.
`allRules: false` exempts it from the Sheet's "All" rows, which hide power
rankings everywhere else.

## Leaving stories out: the rules Sheet

The **RSS** tab of Kyle's Google Sheet (`rules` in `config.json`, link-viewable)
says which stories to drop. Kyle edits it; the next hourly build applies it.

| Team | Look in | Hide if it contains | Unless it contains | Notes |
| --- | --- | --- | --- | --- |
| All | Headline | NHL, MLB, NFL, NBA | | league-wide pieces |
| Lions | Headline | odds | | |

- **Team** is a tab name (Tigers, Lions, Pistons, Red Wings, Cavaliers) or All.
- **Look in**: `Headline`, or `Headline or teaser` to search the one-line
  teaser too. The Athletic's feed carries no author or section, so headline
  and teaser are all there is.
- **Hide if it contains**: words or phrases, comma-separated; any one hides
  the story. Case doesn't matter and it matches inside words ("NFL" catches
  "NFL's", but "bet" would also catch "better").
- **Unless it contains**: optional exceptions, comma-separated — e.g. hide
  "NHL" unless "Red Wings" keeps the league pieces that are about Detroit.
- A row with nothing in "Hide if it contains" is ignored, so notes rows are fine.
- **Team can be a source** on a tab built from several feeds: `USMNT` or
  `Atlanta` on the Soccer tab, `NFL` etc. on Power Rankings.
- **`*` in "Hide if it contains" means every story**, which turns "Unless it
  contains" into a keep-only list. Two keep-only rows for the same source must
  BOTH be met — the USMNT rows keep only stories naming the national team, and
  of those only matches, squads and player roundups.
- **A phrase can't contain a comma** — the comma splits it. "fan, explained"
  becomes "fan" and "explained", and "fan" alone hides every headline with
  "fans" or "fantastic" in it (found while testing, 2026-10-19).
- Rules are separate: a story is hidden if ANY row hides it, and a row's
  "Unless" only rescues it from that row. So "NFL unless Lions" keeps "Week 5
  NFL power rankings: … Lions fall flat" past the league row, and the
  "power rankings" row still hides it.

The starting five rows were worked out from what siftrss had been dropping and
reproduce it exactly (checked story by story on 2026-10-19). The header row
must stay as it is: the build checks it, because a Sheet asked for a tab that
isn't there answers with a different tab instead of an error. If the Sheet
can't be read, the build uses the last good copy (`cache/rules.json`) and says
so in its log; with no copy it stops rather than publish everything.

## Hourly refresh

GitHub has run this account's scheduled builds four to five hours late, or
skipped them, since September 2026 — the night of 2026-10-18 only one of four
three-hourly runs happened. A build started through GitHub's API runs at once,
so **"RSS Feeds Refresh"** (`refresh-script/Code.js`, its own Apps Script
project in Kyle's account) starts `build.yml` every hour from a time-driven
trigger. The workflow's own cron stays as a backup.

It needs a Script Property `GITHUB_TOKEN`: a fine-grained GitHub token scoped
to `kyeill/rss-feeds` only, with **Actions: read and write** and nothing else.
Kyle created and pasted it himself; it is not in the repo. `setup()`, run once
from the editor, asks for permission, installs the trigger and starts one
build. A failure throws, and Apps Script emails Kyle — that is how an expired
token will show up: make a new token, paste it over the old value, done.

It is a separate project from the read list on purpose: that one's Script
Properties hold one entry per story read, and the token is easier to find,
and to keep away from the public web app, on its own.

## Icon and install

The mark is the page itself: a spine with one dot per team, in tab order and
team colour, each beside a headline bar. `python icons.py` draws it (no image
library on this PC, so it is pixel maths with 4x4 supersampling):

- `icon-192.png`, `icon-512.png` — full-bleed, `purpose: any maskable`. The
  mark stays inside the 0.4-radius safe circle, so Android launchers can cut
  it to any shape (the "adaptive icon").
- `icon-mono-512.png` — white on transparent, `purpose: monochrome`, for
  Android 13+ themed icons that recolour to the wallpaper.
- `icon-180.png` — iPhone home screen, the mark 25% larger since iOS only
  rounds the corners.
- The browser-tab icon is an SVG the page draws itself: one dot in the OPEN
  tab's colour plus three bars, which is what still reads at 16px.

`sw.js` caches only the shell: the page is always fetched fresh and the cached
copy is the offline fallback. Icons are served cache-first, so if they change,
bump `CACHE` in `sw.js`.

## Look

**Dark only** (Kyle, 2026-10-19) — no light palette, whatever the device is set to.

**Type mirrors The Athletic** with free stand-ins, since its fonts are licensed
to the NYT (read from its stylesheets on 2026-10-19):

| The Athletic | here | used for |
| --- | --- | --- |
| nyt-franklin | Libre Franklin | tabs (small caps-style uppercase, like its nav), dates, labels, scores, opponents |
| nyt-cheltenham | Source Serif 4 (600) | headlines and teasers |
| RegularSlab | Roboto Slab | the big place / gap / odds figures, Up next opponent |

On a phone the five tabs with their counts are wider than the screen in any
font, so the tab row scrolls and fades at its right edge; the open tab scrolls
into view and swiping changes team.

## Read and unread

Opening a story marks it read, and the mark follows Kyle to every device. An
unread story's date is red; once read, the date and headline turn grey, and the
tab's count drops. A "Mark all N Red Wings stories read" link in the footer
clears the current tab after a confirm, and hides itself at zero. (An "Unread
only" filter existed briefly and went with the filter row.)

The page is static, so the list lives in an Apps Script web app,
"RSS Feeds Read Sync", in Kyle's Google account (`apps-script/Code.js`, one
Script Property per story id). Its `/exec` address is `sync` in `config.json`;
`build.py` writes it into the page. Each browser also keeps a copy in
`localStorage`, so marks show at once and survive a dropped connection; any
mark the server hasn't acknowledged is retried on the next load. The page
re-reads the list on every sign it is back in front (visibilitychange,
pageshow, focus, coming back online) and every two minutes while open —
phones often resume a page from memory without reloading it, and Kyle saw
marks from his computer not reaching his phone (2026-10-18) when only
visibilitychange was used. The footer says "Read list synced 10:35 pm" with
the time of the last successful sync.

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
- **Nothing here knows what a story is about.** The tags are timing, not
  subject: a trade-request story filed an hour after a loss is tagged *Same
  night* like any recap.
- **Every link is paywalled.** It is an Athletic feed; the page shows the
  headline and dek the feed carries and links out.
