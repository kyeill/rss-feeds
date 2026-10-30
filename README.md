# RSS Feeds

Beat writers' stories read against the schedule: each story sits under the last
game finished before it was filed, so the rhythm of the coverage shows.

Live: https://kyeill.github.io/rss-feeds/ · repo: kyeill/rss-feeds

## Files

| file | what it does |
| --- | --- |
| `config.json` | read-list address, rules Sheet, and every section and its feeds |
| `build.py` | reads the feeds, the rules and the schedules; writes the page. Standard library only |
| `template.html` | the whole page: CSS, and the script that lays out the timeline |
| `docs/` | what Pages serves from `main`: the built `index.html`, plus the hand-written `sw.js` and manifest, and the icons |
| `cache/` | committed by the build: `rules.json` (last good rules), `archive/` (posts feeds no longer hold) |
| `apps-script/` | "RSS Feeds Read Sync", the web app holding the read list |
| `refresh-script/` | "RSS Feeds Refresh", which starts the build hourly |
| `icons.py` | draws the icons into `docs/`; run by hand when the mark changes |

```bash
python build.py
```

## How it runs

**Hourly.** GitHub runs this account's scheduled builds hours late, so "RSS Feeds
Refresh" (a time-driven Apps Script trigger) starts `build.yml` through GitHub's
API every hour. The workflow's three-hourly cron is the backup. Each run commits
`docs` and `cache` if anything moved.

The refresh script needs a Script Property `GITHUB_TOKEN`: a fine-grained token
for `kyeill/rss-feeds` only, Actions read and write. Kyle pastes it himself; it
is never in the repo. A failed run throws and Apps Script emails him, which is
how an expired token shows up: make a new one and paste it over the old value.
`setup()`, run once from the editor, installs the trigger.

**When something fails:**

| what | what happens |
| --- | --- |
| timeout, dropped connection, 5xx | retried once |
| a feed still down | the last published page's stories stand in, and the section's footer says "didn't load at the last update". If that lasts for days, the feed's address has probably changed |
| an archived source down | its archive stands in |
| the rules Sheet unreadable | `cache/rules.json` is used; with no copy the build stops rather than publish unfiltered |
| a schedule unreadable | the build fails, and the live page stays as it was |

Each address is asked once per build, a failure included. The outage handling
was tested with every Athletic address forced to 504: all sections kept every
story.

## The page

The **home page** lists each section with its unread count, shaded in the team's
colour when there are any, and the total in the title. No `#` in the address is
home, `#slug` a section, so sections can be bookmarked and the phone's Back button
works. **‹ Home** goes back. On a phone, a quick sideways swipe (60px, twice as far
across as down, under 0.7s) moves between sections.

A section is **Up next** (date, time, network, venue) then the timeline, newest
first. Stories from before the first game run on at the bottom. The timeline
starts at the game the oldest story follows, so a feed's reach sets its length.

Everything is in Detroit time, and a story is placed by the game's start time
rather than its date, so a story at 12:30am stays with the 7pm game.

**Games:** `[n]` numbers regular-season games; preseason is blank, postseason is
`PO`, cup games are unnumbered and named. Records run down the page: hockey
W-L-OT, soccer W-D-L, football W-L (a tie adds a column), others W-L. Results show
overtime ("L SO", "W OT") and baseball's extra innings don't show. Postponed and
cancelled games are dropped; the makeup is its own event. A past game shows no
venue or network, and only finished games and the next one go into the page.

**One network per game:** a US national broadcast (TV before streaming), else
the team's own listing, else `localTv` in config. NHL Network, MLB.TV, MLB
Network, NBA TV, League Pass and NFL+ don't count as national. Soccer: the first
English channel; ESPN lists the Spanish ones beside it.

## Sections

Team sections have `league`, `team` and either `feed` or `sources`. Story-only
sections (Soccer, Power Rankings) have neither `league` nor `team`.

| section | stories from | games | stories since |
| --- | --- | --- | --- |
| Michigan Football | The Athletic, MGoBlog | ESPN | Feb 1 |
| Michigan Basketball | The Athletic, UMHoops, MGoBlog | ESPN | Apr 1 |
| Michigan Hockey | MGoBlog | ESPN | Aug 1 |
| Tottenham Hotspur | The Athletic | ESPN soccer | Jul 1 |
| Detroit Tigers | The Athletic | ESPN | Nov 1 |
| Detroit Lions | The Athletic | ESPN | Mar 1 |
| Detroit Pistons, Cleveland Cavaliers | The Athletic | ESPN | Jul 1 |
| Detroit Red Wings | The Athletic | NHL API | Jul 1 |
| Soccer | The Athletic's USMNT and Atlanta United feeds | none | Jul 1 |
| Power Rankings | Headlines with "power rankings" in the four Detroit feeds; "the briefing" in The Athletic's football feed | none | each league's date |

- **Soccer's brief (Kyle):** USMNT matches and player roundups, no single-player
  deep dives or FIFA politics; Atlanta stories plus at most a weekly MLS roundup,
  The Athletic's "The Verdict". The rules Sheet does this.
- **Power Rankings** reads team feeds because league feeds hold only a week or
  two, while every ranking mentions every team. `allRules: false` exempts it from
  the Sheet's All rows, which hide power rankings elsewhere. Each league's unread
  dates use its team's colour (`palette`).
- **The Briefing** comes from the whole-football feed, as there is no Premier
  League feed (the address 404s). That feed holds about ten days, so matches are
  archived. The Tottenham feed is a second source for older editions.
- **Soccer schedules** are per competition (`SOCCER_COMPS`), asked twice, because
  fixtures need `fixture=true`. The FA Cup answers 500 until the club is in the
  draw; that means no games.

## Michigan's feeds

**MGoBlog** (`mgoblog.com/fbfeed`) covers every sport, has no categories and keeps
only its newest 10 posts.

- **History:** posts are saved in `cache/archive/` (400 days). Feedly's public
  stream API, newest 50 with full text, is merged in on each build, so missed
  builds lose nothing. MGoBlog's robots.txt turns away AI agents, so **its pages
  are never crawled**; posts older than the archive simply aren't here.
- **Sorting** (`sport_of`), first match wins:
  1. Series headlines: "Michigan Hockey", "HockeyCast", "Hoops Preview", "WBB…".
     Basketball patterns are anchored at the start, so a mailbag that mentions
     Hoops stays mixed. These come first because Feedly's copy of some posts
     carries other posts' text.
  2. People a headline names, if exactly one sport's (`load_names`): Michigan's
     ESPN rosters and coaches, plus names from other basketball sources' personnel
     headlines, which beat ESPN to new arrivals. A name football headlines use too
     doesn't count. This is what places "Portal Hello: JP Estrella".
  3. Word counts of terms only one sport uses, with a stray mention allowed.
  Anything left, football or mixed, goes to Michigan Football.

**UMHoops** comes from its WordPress REST API (`/wp-json/wp/v2/posts`). Its firewall
refuses the build at `/feed/`; trying other clients until one passed was ruled out
as evading bot protection. Feedly also carries it, should the API close.

**The Athletic** has no Michigan hockey feed. A college opponent is shown as its
school alone.

## The rules Sheet

The **RSS** tab of Kyle's Google Sheet (`rules` in config) decides what's hidden.
He edits it; the next build applies it.

| Team | Look in | Hide if it contains | Unless it contains |
| --- | --- | --- | --- |
| All | Headline | podcast, odds | |
| Detroit Lions | Headline | nfl | detroit, lions |

- **Team:** a section's name, its old short name (`aka`: "Tigers", "Tottenham"),
  All, or a source label (`MGoBlog`, `UMHoops`, `The Athletic`, `USMNT`, `Atlanta`).
- **Look in:** `Headline`, or `Headline or teaser`. The feeds carry nothing else.
- **Hide / Unless:** comma-separated phrases, any case, matched inside words: "nfl"
  catches "NFL's", and "bet" would catch "better". A phrase can't contain a comma.
- **`*`** in Hide means every story, making Unless a keep-only list. Two keep-only
  rows for one source must both be met.
- A story is hidden if any row hides it; a row's Unless only rescues it from that row.
- A row with nothing in Hide is ignored, so note rows are fine.
- The first four column headers must stay as they are: a Sheet asked for a missing
  tab answers with another tab, not an error, so the build checks.

## Read and unread

Opening a story, or its ×, marks it read on every device; so does "Mark all N … stories
read" in the footer. An unread date is in the team's colour, a read story is grey.

The page is static, so the list lives in "RSS Feeds Read Sync" (one Script Property
per story id, `r:<id>`). Each browser keeps a copy in `localStorage` and queues
unsent marks, and the page re-reads the list whenever it comes back to the front and
every two minutes, because phones resume pages without reloading. Story ids are The
Athletic's article number, or a hash of the link for other sources.

Deploy a change to the script from `apps-script/`:

```bash
clasp push -f
clasp create-deployment -i <the id in config.json's sync address> -d "what changed"
```

`create-deployment -i` repoints the existing deployment, so the address never
changes. `.clasp.json` is gitignored. From `refresh-script/`, clasp 3 needs the full
Windows path: `clasp -P "$(cygpath -w "$PWD")" push -f`.

## Look

Dark only. Fonts are free stand-ins for The Athletic's: Libre Franklin (nyt-franklin:
labels, dates, scores), Source Serif 4 (nyt-cheltenham: headlines, teasers), Roboto
Slab (RegularSlab: section names).

Colours are CSS tokens per `data-team` in `template.html`, and the `--accent-text`
shade must stay readable on the dark ground. Michigan maize, Tottenham navy, Tigers
orange, Lions blue, Pistons teal, Red Wings red, Cavaliers old gold, Soccer Atlanta's
dark red, Power Rankings silver.

**Icons** (`python icons.py`, pixel maths since this PC has no image library):
`icon-192/512` are maskable, `icon-mono-512` is for Android themed icons, `icon-180`
for iPhone. The browser-tab icon is an SVG the page draws in the section's colour.
`sw.js` always fetches the page fresh and serves icons cache-first, so bump `CACHE`
if they change.

## Adding a section

Add it to `config.json`, then add a `data-team` colour line to `template.html`. Team
sections need a `league` that `season_for` and `schedule` know. The Athletic's feed
addresses can't be guessed; Kyle supplies them.

## Decisions

Kyle's calls, so they don't get re-added:

- **Removed:** story timing tags and the "after" line, chapters, gap labels, footer
  credits, tagline, filter row, tab row, and notes on Up next beyond the next game.
- **Place, games back and playoff odds** came off the team sections on 2026-10-29
  ("maybe will add back something later"). The code was removed on 2026-10-30;
  the last version with it is commit `aa2e43f`.
- **Teasers** stay The Athletic's own. Better ones would need paywalled article text.
- **Extracting the power rankings** as data was skipped: feed items hold only a
  headline, and the articles are paywalled and off-limits (below).

## Traps

- **The Athletic and NYT:** every link is paywalled and nytimes.com's robots.txt
  disallows Anthropic's agents, including Claude-User. Feeds only; no article pages.
- **`clasp create-script` overwrites `appsscript.json`.** The manifest must keep
  `executeAs: USER_DEPLOYING` and `access: ANYONE_ANONYMOUS`, or the page's calls fail.
- **The read list's address is public** (it is in the page). Accepted: it holds only
  article numbers, takes short ids, at most 1000 per call, and forgets after 400 days.
- **Clearing a mark on the server alone doesn't stick:** a browser that has it resends it.
- **Testing the ×:** a click in a local preview marks a real story read through the
  live read list. Stub `window.fetch` first, then clear `rssf:read`/`rssf:pending`.
- **Merging builds:** CI commits `docs` and `cache` hourly, so rebases conflict there.
  Take either side, rerun `python build.py`, and confirm no `<<<<<<<` remains before
  adding; a conflicted `docs/index.html` once crashed CI.
