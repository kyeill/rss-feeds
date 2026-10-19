"""Build the site: beat-writer RSS feeds read against each team's schedule.

One page, a tab per feed. Sources, all public:

  * The Athletic's own team feeds (nytimes.com/athletic/rss/<league>/<team>/),
    200 items each, always the newest;
  * Kyle's rules Sheet, which says which of those stories to leave out;
  * NHL: the league's own schedule and standings endpoints;
  * MLB, NFL, NBA: ESPN's team schedules, standings and (NFL, NBA) power
    index for playoff odds; MLB's odds ride along in its standings;
  * NHL playoff odds from Hockey-Reference, at most twice a day (cache/).

Every run re-asks everything but Hockey-Reference and rewrites
docs/index.html from template.html.

    python build.py
"""

import csv
import email.utils
import io
import json
import html
import hashlib
import re
import pathlib
import datetime as dt
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "rss-feeds build (github.com/kyeill/rss-feeds)"}


FETCHED = {}


def fetch(url):
    """One retry after a timeout or dropped connection: the build makes ~40
    requests an hour, and one slow answer shouldn't fail it (and email Kyle).
    An HTTP error (403, 404, 500) is an answer, not a hiccup, and isn't retried.
    Each address is downloaded once per build: the names step reads the
    basketball feeds before their section does."""
    if url in FETCHED:
        return FETCHED[url]
    FETCHED[url] = _download(url)
    return FETCHED[url]


def _download(url):
    req = urllib.request.Request(url, headers=UA)
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError:
            raise
        except (TimeoutError, urllib.error.URLError, ConnectionError):
            if attempt == 2:
                raise


def story_id(link):
    """A short, stable key for the read list. The Athletic's links carry their
    own article number (/athletic/7699924/...); anything else is hashed."""
    m = re.search(r"/athletic/(\d+)/", link)
    return m.group(1) if m else hashlib.sha1(link.encode()).hexdigest()[:12]


def read_feed(url, since):
    """Pull title / dek / link / time out of the RSS. No library: the shape is
    fixed, and a dependency here would have to be installed on every CI run."""
    raw = fetch(url)
    items, seen = [], set()
    for block in re.findall(r"<item>(.*?)</item>", raw, re.S):

        def tag(name):
            m = re.search(
                r"<%s>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</%s>" % (name, name), block, re.S
            )
            return html.unescape(m.group(1).strip()) if m else ""

        pub = tag("pubDate")
        if not pub:
            continue
        # RFC 822 dates: The Athletic writes "GMT", MGoBlog and UMHoops "+0000"
        when = email.utils.parsedate_to_datetime(pub).astimezone(dt.timezone.utc)
        link = tag("link")
        if when.date().isoformat() < since or link in seen:
            continue
        seen.add(link)
        title = tag("title")
        text = plain(tag("description") + " " + tag("content:encoded"))
        items.append(
            {
                "id": story_id(link),
                "title": title,
                "dek": teaser(title, plain(tag("description"))),
                "link": link,
                "iso": when.isoformat(),
                "_text": text,           # for sorting MGoBlog by sport; never published
            }
        )
    items.sort(key=lambda a: a["iso"])
    return items


def read_wordpress(site, since):
    """A WordPress site's posts from its public REST API (/wp-json/wp/v2/posts),
    newest first, up to 300 since the season's start. UMHoops' firewall turns
    the build away at /feed/ but serves its API -- the site's own public
    interface, asked for under the build's own name."""
    items = []
    for page in (1, 2, 3):
        url = (f"{site.rstrip('/')}/wp-json/wp/v2/posts?per_page=100&page={page}"
               f"&after={since}T00:00:00&_fields=id,date_gmt,link,title,excerpt")
        try:
            posts = json.loads(fetch(url))
        except urllib.error.HTTPError as err:
            if err.code == 400 and page > 1:  # past the last page
                break
            raise
        for p in posts:
            title = plain(p["title"]["rendered"])
            items.append({
                "id": story_id(p["link"]),
                "title": title,
                "dek": teaser(title, plain(p["excerpt"]["rendered"])),
                "link": p["link"],
                "iso": p["date_gmt"] + "+00:00",
                "_text": "",
            })
        if len(posts) < 100:
            break
    items.sort(key=lambda a: a["iso"])
    return items


def read_feedly(feed_url):
    """The newest 50 posts Feedly holds for a feed, from its public stream API.

    MGoBlog's own feed keeps only its newest 10 posts (about four days), and
    its robots.txt turns away AI agents (ClaudeBot, ChatGPT-User), so its
    article pages are not crawled for history. Feedly -- Kyle's own reader --
    keeps what the feed has carried, full text included, and serves 50 without
    a login: about three weeks. Merged into the archive on every build, so a
    run of missed builds can't lose a post either."""
    url = ("https://cloud.feedly.com/v3/streams/contents?count=50&streamId="
           + urllib.parse.quote("feed/" + feed_url, safe=""))
    items = []
    for it in json.loads(fetch(url)).get("items", []):
        link = ((it.get("alternate") or [{}])[0]).get("href") or it.get("originId") or ""
        if not link.startswith("http"):
            continue
        title = plain(it.get("title") or "")
        body = (it.get("content") or it.get("summary") or {}).get("content", "")
        when = dt.datetime.fromtimestamp(it["published"] / 1000, dt.timezone.utc)
        items.append({"id": story_id(link), "title": title, "dek": teaser(title, plain(body)),
                      "link": link, "iso": when.isoformat(), "_text": plain(body)})
    return items


def plain(markup):
    """Markup to one line of text."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    return re.sub(r"\s+", " ", text).strip()


def teaser(title, text):
    """A one- or two-line teaser. The Athletic's descriptions already are one;
    MGoBlog's carry the whole post, led by its title and byline ("Brian October
    16th, 2026 at 2:57 PM"), and UMHoops' end "The post ... appeared first on
    UMHoops." All of that goes, and anything long is cut at a word."""
    if text.startswith(title):
        text = text[len(title):].strip()
    m = re.match(r".{0,80}?\b\w+ \d{1,2}(?:st|nd|rd|th), \d{4} at \d{1,2}:\d{2} [AP]M\s*", text)
    if m:
        text = text[m.end():]
    text = re.sub(r"\s*The post .* appeared first on .*$", "", text)
    if len(text) > 240:
        text = text[:240].rsplit(" ", 1)[0].rstrip(",;:") + "\u2026"
    return text


# ---- Kyle's rules: which stories to leave out ---------------------------------

RULES_HEADER = ["Team", "Look in", "Hide if it contains", "Unless it contains", "Notes"]
RULES_CACHE = HERE / "cache" / "rules.json"


BASKETBALL = re.compile(r"basketball|hoops|rebound|three-pointer|3-pointer|\bthrees\b|free throw|layup|dunk|kenpom|"
                        r"torvik|crisler|sweet 16|elite eight|final four|point guard|\bwbb\b|jumper|and-one|\bpaint\b|"
                        r"backcourt|frontcourt|shot clock|\bbpi\b|pick-and-roll|pick and roll|\brim\b|big man|"
                        r"ball screen|boynton|\bppg\b|\brpg\b|post-up")
FOOTBALL = re.compile(r"football|touchdown|quarterback|\bqb\b|\byards\b|rushing|passing game|\bsack|linebacker|"
                      r"cornerback|\bpunt|field goal|offensive line|defensive line|big house|tailback|receiver|"
                      r"interception|fumble|first down|play-action|\bsnap|line of scrimmage|end zone")
HOCKEY = re.compile(r"hockey|goalie|power play|penalty kill|\bpuck|faceoff|shots on goal|blue line|yost|\bncha\b|\bccha\b")


# Names that settle an MGoBlog headline the word count can't ("Portal Hello: JP
# Estrella" names no basketball terms at all). Filled once per build by
# load_names(): {"basketball": {...}, "hockey": {...}, "football": {...}}.
NAMES = {"basketball": set(), "hockey": set(), "football": set()}

# Capitalised words in a basketball headline that are never part of a person's name.
NOT_NAMES = set("""michigan michigans state big ten final four ncaa nba draft march madness sweet elite
eight national championship photo gallery open thread video podcast exhibition europe game preview
recap college basketball summer league portal transfer head coach guard forward center wolverines
spartans the and of for with from after vs at in on how why what who when where is are will can
mega superbet lithuania oregon arizona uconn duke purdue illinois indiana iowa maryland minnesota
nebraska northwestern ohio penn rutgers ucla usc washington wisconsin eastern western central
fab five crisler ann arbor detroit pistons hoops recruiting roundup board hot tracker roster scout every player
magic""".split())


def name_key(text):
    """Lower case, punctuation dropped: MGoBlog writes "JP Estrella", ESPN "J.P. Estrella"."""
    return " ".join(re.sub(r"[^a-z ]", "", text.lower().replace(".", "").replace("-", " ")).split())


# A basketball headline about a person joining, leaving or being signed -- the
# only kind whose names are taken (others name LeBron, Madison Square Garden...).
PERSONNEL = re.compile(r"commit|transfer|portal|sign|signee|lands|adds|hire|joins|hello|"
                       r"visit|offer|recruit|declare|withdraw|return|enter|staff|assistant|depart|leav", re.I)


def load_names(basketball_titles, football_titles=()):
    """Michigan's current rosters and coaches from ESPN, by sport, plus names
    from the basketball sources' own headlines -- they write about every new
    arrival (a transfer, a commit, a new assistant) before ESPN's roster has
    them. A headline-derived name is two or three capitalised words, none of
    them a team, place or basketball word, taken only from personnel headlines
    (joining, leaving, signing), and dropped if football headlines use it too
    -- the basketball feeds also cover Sherrone Moore and Bryce Underwood."""
    paths = {"basketball": "basketball/mens-college-basketball", "hockey": "hockey/mens-college-hockey",
             "football": "football/college-football"}
    for sport, path in paths.items():
        try:
            d = espn_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams/130/roster")
        except Exception as err:
            print(f"  ! {sport} roster unreadable ({err})")
            continue
        people = d.get("athletes", [])
        if people and isinstance(people[0], dict) and "items" in people[0]:   # football groups by position
            people = [a for group in people for a in group["items"]]
        names = [a.get("fullName") or a.get("displayName") or "" for a in people]
        names += [f"{c.get('firstName', '')} {c.get('lastName', '')}" for c in d.get("coach", [])]
        NAMES[sport] |= {name_key(n) for n in names if len(name_key(n).split()) >= 2}
    football_words = " " + " ".join(name_key(t) for t in football_titles) + " "
    for title in basketball_titles:
        if not PERSONNEL.search(title):
            continue
        for m in re.finditer(r"\b[A-Z][\w'’.]*(?:\s+(?:[A-Z][\w'’.]*|Jr\.?|II|III)){1,2}", title):
            words = name_key(m.group(0)).split()
            if len(words) >= 2 and not any(w in NOT_NAMES for w in words):
                key = " ".join(words)
                # a name football headlines use too (Sherrone Moore, Warde Manuel) settles nothing
                if key not in NAMES["football"] and " " + key + " " not in football_words:
                    NAMES["basketball"].add(key)
    print(f"  names: {', '.join(f'{k} {len(v)}' for k, v in NAMES.items())}")


def named(head):
    """The one sport whose people a headline names, or None (none, or more than one)."""
    key = " " + name_key(head) + " "
    hits = {sport for sport, names in NAMES.items() if any(" " + n + " " in key for n in names)}
    return hits.pop() if len(hits) == 1 else None


def sport_of(title, text):
    """Which section an MGoBlog post belongs to: "basketball", "hockey" or
    "other" (football and everything else -- podcasts, mixed posts, other
    sports). Its feed has no categories, but it carries the whole post, so this
    counts terms only one sport uses. MGoBlog names its series consistently
    ("Michigan Hockey Game #6", "Michigan HockeyCast", "Hoops Preview", "WBB"),
    and a headline beats the text -- Feedly's copy of some posts carries other
    posts' text along -- so such a headline decides first. Otherwise a post is
    basketball or hockey when it has some of that sport's terms and next to
    none of the others' (hockey and basketball share "rebound" and "paint", so
    each tolerates a stray one). Between the two, a headline naming a current
    player or coach of exactly one sport decides (see load_names) -- that is
    what puts "Portal Hello: JP Estrella", whose text has no basketball terms,
    in Basketball. Checked on 21 page samples and Feedly's 50 posts."""
    t = (title + " " + text).lower()
    head = title.lower()
    if re.search(r"michigan hockey|^hockey\b|hockey preview|hockeycast", head):
        return "hockey"
    # anchored at the start: "Hoops Preview:", "WBB Preview:" -- a mailbag that "Talks
    # Coaches, Blame, Hoops, and Hockey" mid-headline is a mixed post
    if re.search(r"^(hoops|wbb)\b|^michigan (men's |women's )?basketball|hoops preview|wbb preview", head):
        return "basketball"
    # then the people a headline names: "Portal Hello: JP Estrella" is a basketball post
    person = named(title)
    if person in ("basketball", "hockey"):
        return person
    if person == "football":
        return "other"
    bb = len(BASKETBALL.findall(t))
    hk = len(HOCKEY.findall(t))
    fb = len(FOOTBALL.findall(t))
    if bb >= 3 and fb <= bb * 0.15 and hk <= max(1, bb * 0.2):   # one stray mention allowed
        return "basketball"
    if hk >= 3 and fb <= hk * 0.15 and bb <= max(1, hk * 0.6):
        return "hockey"
    return "other"


ARCHIVE = HERE / "cache" / "archive"


def remembered(src, items):
    """A feed that only holds its newest few posts (MGoBlog keeps 10, UMHoops 6)
    would lose a story off the page within days, so these feeds' posts are kept
    in cache/archive/, one file per feed, and every build adds what's new. Each
    post's sport is decided once, while its full text is at hand (posts saved
    before hockey had its own section carry only a basketball flag; their
    headline settles hockey)."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE / (re.sub(r"\W+", "-", src["feed"].split("//", 1)[1]).strip("-") + ".json")
    kept = {a["id"]: a for a in (json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])}
    for a in items:
        kept[a["id"]] = {k: v for k, v in a.items() if k != "_text"} | {"sport": sport_of(a["title"], a["_text"])}
    for a in kept.values():
        if "sport" not in a:
            a["sport"] = "basketball" if a.pop("bb", False) else \
                "hockey" if re.match(r"(michigan hockey|hockey)\b", a["title"].lower()) else "other"
    cutoff = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    out = sorted((a for a in kept.values() if a["iso"] >= cutoff), key=lambda a: a["iso"])[-800:]
    path.write_text(json.dumps(out, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    return out


def gather(sources, league, include=()):
    """Stories from several feeds, each labelled with its source, newest kept
    from the season's start, a story in two feeds kept once (first source
    wins). `sport` keeps only MGoBlog's basketball posts, or all but them."""
    seen, articles = set(), []
    for src in sources:
        since, _ = season_for(src.get("league", league), dt.date.today())
        try:
            items = read_wordpress(src["feed"], since) if src.get("type") == "wordpress" else read_feed(src["feed"], since)
        except Exception as err:
            # one source down shouldn't blank a section; an archived one keeps what it had
            print(f"  ! {src['label']} unreadable ({err}); skipped this run")
            items = []
        if src.get("feedly"):
            try:
                items += read_feedly(src["feed"])
            except Exception as err:
                print(f"  ! Feedly's copy of {src['label']} unreadable ({err})")
        if src.get("archive"):
            items = [a for a in remembered(src, items) if a["iso"][:10] >= since]
        for a in items:
            if a["id"] in seen:
                continue
            if include and not any(w in a["title"].lower() for w in include):
                continue
            if src.get("sport") and (a.get("sport") or sport_of(a["title"], a.get("_text", ""))) != src["sport"]:
                continue
            seen.add(a["id"])
            articles.append({k: v for k, v in a.items() if k not in ("_text", "bb", "sport")} | {"src": src["label"]})
    return articles


def read_rules():
    """The rows of Kyle's rules Sheet, or the last good copy.

    The rules are the "RSS" tab of Kyle's link-viewable Google Sheet: `rules`
    in config.json is that tab's address, gid and all, read as CSV. Its header must be exactly RULES_HEADER: a
    Google Sheet asked for something that isn't there answers with whatever
    it has rather than an error, so a wrong header means a wrong sheet.

    When the Sheet can't be read, the last good copy in cache/ is used and the
    build says so; with no copy at all the build stops rather than publish
    every story unfiltered.
    """
    url = CONFIG.get("rules")
    try:
        if not url:
            raise ValueError("no rules Sheet in config.json")
        sid = re.search(r"/d/([\w-]+)", url).group(1)
        tab = re.search(r"gid=(\d+)", url)
        gid = tab.group(1) if tab else "0"
        rows = list(csv.reader(io.StringIO(fetch(
            f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"))))
        if not rows:
            raise ValueError("the rules tab is empty")
        if [c.strip() for c in rows[0][:len(RULES_HEADER)]] != RULES_HEADER:
            raise ValueError(f"the first row should read {RULES_HEADER}, not {rows[0][:5]}")
        rules = []
        for r in rows[1:]:
            r = [c.strip() for c in r] + [""] * len(RULES_HEADER)
            hide = [w.strip().lower() for w in r[2].split(",") if w.strip()]
            if not hide:
                continue                      # a blank or note-only row
            rules.append({
                "team": r[0] or "All",
                "teaser": "teaser" in r[1].lower(),
                "hide": hide,
                "unless": [w.strip().lower() for w in r[3].split(",") if w.strip()],
            })
        RULES_CACHE.parent.mkdir(exist_ok=True)
        RULES_CACHE.write_text(json.dumps(rules, indent=1) + "\n", encoding="utf-8")
        return rules
    except Exception as err:
        if not RULES_CACHE.exists():
            raise SystemExit(f"rules Sheet unreadable ({err}) and no saved copy -- not publishing unfiltered")
        print(f"  ! rules Sheet unreadable ({err}); using the copy saved in cache/rules.json")
        return json.loads(RULES_CACHE.read_text(encoding="utf-8"))


def hidden(article, team, rules, use_all=True):
    """Does any rule hide this story? A rule applies when its Team is this
    tab, All (unless the tab opts out), or -- on a tab built from several
    feeds -- the story's own source label ("USMNT", "Atlanta"). Matching
    ignores case and finds the words anywhere, so "NFL" also catches "NFL's".
    A "*" in "Hide if it contains" matches every story, which turns that
    row's "Unless" list into a keep-only list. A story survives only if no
    row hides it, so two keep-only rows for one source must both be met."""
    names = {team.lower(), (article.get("src") or "").lower()} - {""}
    if use_all:
        names.add("all")
    for rule in rules:
        if rule["team"].lower() not in names:
            continue
        text = (article["title"] + (" " + article["dek"] if rule["teaser"] else "")).lower()
        if any(w == "*" or w in text for w in rule["hide"]) and not any(w in text for w in rule["unless"]):
            return True
    return False


def nhl_standing(abbrev, played):
    """Where the club stands: division place, and how far it is from the
    playoff line. A conference sends the top three of each division plus two
    wild cards, so a team outside is as far back as the NEARER of its
    division's third place and the conference's second wild card; a team
    inside is as far clear as it is above the conference's first team out.

    `played` is the club's finished regular-season games from its schedule:
    a table that disagrees (last season's, before a new one starts) is
    not shown."""
    table = json.loads(fetch("https://api-web.nhle.com/v1/standings/now"))["standings"]
    us = next(t for t in table if t["teamAbbrev"]["default"] == abbrev)
    conf = [t for t in table if t["conferenceName"] == us["conferenceName"]]
    inside = lambda t: t["divisionSequence"] <= 3 or 0 < t["wildcardSequence"] <= 2
    if inside(us):
        first_out = next((t for t in conf if t["wildcardSequence"] == 3), None)
        gap = us["points"] - first_out["points"] if first_out else None
    else:
        third = next(t for t in conf if t["divisionName"] == us["divisionName"] and t["divisionSequence"] == 3)
        wc2 = next(t for t in conf if t["wildcardSequence"] == 2)
        gap = min(third["points"], wc2["points"]) - us["points"]
    current = abs(us["gamesPlayed"] - played) <= 1
    return {
        "place": us["divisionSequence"] if current else None,
        "division": us["divisionName"] + " Division",
        "inside": inside(us),
        "gap": gap if current else None,
        "unit": "Point",
        "odds": read_odds(us["teamName"]["default"], us["points"]),
    }


ODDS_URL = "https://www.hockey-reference.com/friv/playoff_prob.fcgi"
ODDS_CACHE = HERE / "cache" / "nhl-odds.json"


def read_odds(name, points):
    """Playoff odds from Hockey-Reference, or None when there are none to show.

    MoneyPuck asks not to be scraped, so it stays out (same call as the
    standings app). Hockey-Reference's robots.txt allows this page and asks
    for a 3-second crawl delay; the build runs every three hours, so the page
    is fetched at most every 12 hours and the copy kept in cache/.

    The page only starts a season once every team has played 10 games; until
    then it still shows last season, with the odds cells blank. So a number
    counts only if the page's current points for the team match the NHL's.
    """
    cached = json.loads(ODDS_CACHE.read_text(encoding="utf-8")) if ODDS_CACHE.exists() else {}
    age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(cached.get("fetched", "2000-01-01T00:00:00+00:00"))
    if age > dt.timedelta(hours=12):
        try:
            page = fetch(ODDS_URL)
        except OSError as err:
            print(f"  odds: Hockey-Reference unreachable ({err}); keeping the cached copy")
        else:
            teams = {}
            # pull name, points and probability out of the same row, so a blank
            # cell can't shift a value onto the wrong team
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
                cell = lambda stat: re.search(r'data-stat="%s"[^>]*>(?:<a[^>]*>)?([^<]*)<' % stat, row)
                team, pts, prob = cell("team_name"), cell("points_current"), cell("prob_playoffs")
                if team and pts and prob and pts.group(1).strip().isdigit():
                    teams[html.unescape(team.group(1).strip())] = {
                        "points": int(pts.group(1)),
                        "pct": prob.group(1).strip().rstrip("%") or None,
                    }
            cached = {"fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "teams": teams}
            ODDS_CACHE.parent.mkdir(exist_ok=True)
            ODDS_CACHE.write_text(json.dumps(cached, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    row = cached.get("teams", {}).get(name)
    if not row or row["points"] != points or row["pct"] is None:
        return None
    return float(row["pct"])


def nhl_tv(broadcasts, local_tv):
    """One network per game, the one Kyle would turn to in Michigan: a US
    national broadcast if there is one, otherwise the club's local channel.
    NHL Network doesn't count as national -- its games stay on the local
    channel too. A game with no broadcasts at all (some preseason) shows none."""
    national = [
        b["network"]
        for b in sorted(broadcasts, key=lambda b: b.get("sequenceNumber", 0))
        if b.get("market") == "N" and b.get("countryCode") == "US" and b.get("network") != "NHLN"
    ]
    return national[0] if national else (local_tv if broadcasts else "")


def nhl_schedule(abbrev, season, local_tv):
    """The club's whole season: preseason, regular season, finished or not."""
    url = f"https://api-web.nhle.com/v1/club-schedule-season/{abbrev}/{season}"
    games = []
    for g in json.loads(fetch(url))["games"]:
        home = g["homeTeam"]["abbrev"] == abbrev
        us, them = (
            (g["homeTeam"], g["awayTeam"]) if home else (g["awayTeam"], g["homeTeam"])
        )
        games.append(
            {
                "id": g["id"],
                "date": g["gameDate"],
                "startUTC": g.get("startTimeUTC"),
                "type": g["gameType"],          # 1 preseason, 2 regular, 3 playoffs
                "state": g["gameState"],
                "home": home,
                "opp": them["abbrev"],
                "oppName": them["commonName"]["default"],
                "oppPlace": them["placeName"]["default"],
                "ds": us.get("score"),
                "os": them.get("score"),
                "last": (g.get("gameOutcome") or {}).get("lastPeriodType"),
                "venue": g["venue"]["default"],
                "tv": nhl_tv(g.get("tvBroadcasts", []), local_tv),
            }
        )
    games.sort(key=lambda g: g["startUTC"] or g["date"])
    return games


# ---- MLB, NFL, NBA: ESPN ---------------------------------------------------

ESPN = {"mlb": "baseball/mlb", "nfl": "football/nfl", "nba": "basketball/nba",
        "cfb": "football/college-football", "cbb": "basketball/mens-college-basketball",
        "chky": "hockey/mens-college-hockey"}

# How many teams per conference (league, for MLB) make the playoffs, and
# whether winning the division guarantees a place. The NBA's line is the top
# six: seeds 7-10 only reach the play-in.
SPOTS = {"mlb": (6, True), "nfl": (7, True), "nba": (6, False)}

# "National" in ESPN's listing but not the channel to watch: out-of-market
# packages, and cable channels whose games the local carrier shows too.
NOT_NATIONAL = {"MLB.TV", "MLBN", "MLB Network", "NBA TV", "NBA League Pass", "NFL+"}


def espn_json(url):
    return json.loads(fetch(url))


def espn_tv(broadcasts, home, local_tv):
    """One network: a national broadcast if there is one (TV before
    streaming), else this team's own local listing, else its usual local
    channel from config (ESPN lists none for most Pistons and Cavaliers games)."""
    def name(b):
        return (b.get("media") or {}).get("shortName") or ""
    national = sorted(
        (b for b in broadcasts
         if (b.get("market") or {}).get("type") == "National" and name(b) and name(b) not in NOT_NATIONAL),
        key=lambda b: (b.get("type") or {}).get("shortName") != "TV",
    )
    ours = [b for b in broadcasts if (b.get("market") or {}).get("type") == ("Home" if home else "Away") and name(b)]
    return name(national[0]) if national else name(ours[0]) if ours else local_tv


def espn_schedule(league, abbrev, season, local_tv):
    """Preseason, regular season and postseason. ESPN's team schedule needs
    an explicit seasontype, and its scores are {"value": 3.0} objects."""
    games = []
    for seasontype in (1, 2, 3):
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[league]}/teams/{abbrev}/schedule"
               f"?season={season}&seasontype={seasontype}")
        for e in espn_json(url).get("events", []):
            comp = e["competitions"][0]
            status = comp["status"]["type"]
            if status["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                continue                      # the makeup date is its own event
            us = next(c for c in comp["competitors"] if abbrev in (c["team"]["abbreviation"], c["team"]["id"]))
            them = next(c for c in comp["competitors"] if c is not us)
            done = bool(status.get("completed"))
            score = lambda c: int((c.get("score") or {}).get("value", 0)) if done else None
            # "Final/OT", "Final/2OT"; baseball's "Final/10" is extra innings, not shown
            detail = status.get("detail") or ""
            last = detail.split("/", 1)[1] if done and "/" in detail and "OT" in detail else None
            start = e["date"] if len(e["date"]) > 17 else e["date"].replace("Z", ":00Z")
            home = us.get("homeAway") == "home"
            games.append({
                "id": e["id"],
                "date": start[:10],
                "startUTC": start,
                "tbd": comp.get("timeValid") is False,
                "type": seasontype,
                "home": home,
                "opp": them["team"]["abbreviation"],
                # pros read city + nickname ("Phoenix" "Suns"); a college team is just
                # its school ("Penn State"), which ESPN puts in location
                "oppName": them["team"].get("location", "") if league in SCHOOLS
                           else them["team"].get("name") or them["team"].get("shortDisplayName", ""),
                "oppPlace": "" if league in SCHOOLS else them["team"].get("location", ""),
                "ds": score(us),
                "os": score(them),
                "last": last,
                "venue": (comp.get("venue") or {}).get("fullName", ""),
                "tv": espn_tv(comp.get("broadcasts") or [], home, local_tv),
            })
    games.sort(key=lambda g: g["startUTC"])
    return games


def division_label(name):
    """"American League Central" -> "AL Central"; the NBA's bare "Central" ->
    "Central Division"; the NFL's "NFC North" stays."""
    name = name.replace("American League", "AL").replace("National League", "NL")
    return name if name.split()[0] in ("AL", "NL", "AFC", "NFC") else name + " Division"


def espn_standing(league, abbrev, season, played):
    """Division place and games from the playoff line, like the NHL's but in
    games: a team outside is as far back as the nearer of the last playoff
    seed and (where winning it is a ticket) its division's leader; a team
    inside is as far clear as it is ahead of the first team out.

    ESPN's table follows ESPN's idea of the current season -- the NBA's still
    shows preseason records the week before opening night, MLB's shows the
    finished season through the winter. A table whose games played disagree
    with the schedule's is not shown; the odds still are when they belong to
    this season."""
    data = espn_json(f"https://site.api.espn.com/apis/v2/sports/{ESPN[league]}/standings?level=3")
    rows = []

    def walk(node, trail):
        for child in node.get("children", []):
            walk(child, trail + [child.get("name", "")])
        for e in (node.get("standings") or {}).get("entries", []):
            st = {s.get("name"): s for s in e.get("stats", []) if s.get("name")}
            num = lambda k: float((st.get(k) or {}).get("value") or 0)
            rows.append({
                "abbr": e["team"]["abbreviation"], "conf": trail[0], "div": trail[-1],
                "w": num("wins"), "l": num("losses"), "t": num("ties"),
                "seed": num("playoffSeed") or 99, "pct": num("winPercent"),
                "odds": (st.get("playoffPercent") or {}).get("displayValue"),
            })

    walk(data, [])
    us = next(r for r in rows if r["abbr"] == abbrev)
    conf = sorted((r for r in rows if r["conf"] == us["conf"]), key=lambda r: r["seed"])
    div = sorted((r for r in conf if r["div"] == us["div"]), key=lambda r: (-r["pct"], r["seed"]))
    spots, div_ticket = SPOTS[league]
    behind = lambda a, b: ((a["w"] - b["w"]) + (b["l"] - a["l"])) / 2      # b's games behind a
    inside = us["seed"] <= spots
    if inside:
        first_out = conf[spots] if len(conf) > spots else None
        gap = behind(us, first_out) if first_out else None
    else:
        gap = behind(conf[spots - 1], us)
        if div_ticket:
            gap = min(gap, behind(div[0], us))

    current = abs((us["w"] + us["l"] + us["t"]) - played) <= 1
    odds = None
    if league == "mlb":
        if current and us["odds"]:
            odds = float(us["odds"].rstrip("%"))
    else:
        pi = espn_json(f"https://site.web.api.espn.com/apis/fitt/v3/sports/{ESPN[league]}/powerindex")
        if (pi.get("currentSeason") or {}).get("year") == season:
            names = {c["name"]: c["names"] for c in pi.get("categories", [])}
            for t in pi.get("teams", []):
                if t["team"]["abbreviation"] == abbrev:
                    for c in t.get("categories", []):
                        proj = dict(zip(names.get(c["name"], []), c.get("values", [])))
                        if isinstance(proj.get("probmakeplayoffs"), (int, float)):
                            odds = float(proj["probmakeplayoffs"])
    if gap is not None and gap == int(gap):
        gap = int(gap)
    return {
        "place": div.index(us) + 1 if current else None,
        "division": division_label(us["div"]),
        "inside": inside,
        "gap": gap if current else None,
        "unit": "Game",
        "odds": odds,
    }


# ---- Soccer: ESPN, one competition at a time ------------------------------

# Every competition a club can play in a season. ESPN's soccer schedules are
# per competition, and one the club isn't in answers with nothing (or, for
# the FA Cup before January, a 500) -- both mean "no games here".
SOCCER_COMPS = [("eng.1", "Premier League"), ("eng.league_cup", "League Cup"), ("eng.fa", "FA Cup"),
                ("uefa.champions", "Champions League"), ("uefa.europa", "Europa League"),
                ("uefa.europa.conf", "Conference League")]
LEAGUE_COMP = "eng.1"

# ESPN lists the Spanish-language channels alongside; Kyle watches in English.
SPANISH = {"Universo", "Telemundo", "UniMás", "UniMas", "TUDN", "ESPN Deportes", "Peacock (Spanish)"}
TV_NAMES = {"USA Net": "USA Network"}


def soccer_tv(broadcasts):
    """One channel: English TV first (NBC, USA), else English streaming (Peacock)."""
    def name(b):
        return (b.get("media") or {}).get("shortName") or ""
    english = [b for b in broadcasts if name(b) and name(b) not in SPANISH]
    english.sort(key=lambda b: (b.get("type") or {}).get("shortName") != "TV")
    return TV_NAMES.get(name(english[0]), name(english[0])) if english else ""


def soccer_schedule(team_id, season):
    """Results and fixtures in every competition. A team schedule returns played
    games by default and upcoming ones only with fixture=true, so each
    competition is asked twice."""
    games, seen = [], set()
    for comp, comp_name in SOCCER_COMPS:
        for extra in ("", "&fixture=true"):
            url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{comp}/teams/{team_id}/schedule"
                   f"?season={season}{extra}")
            try:
                events = espn_json(url).get("events", [])
            except Exception as err:          # the FA Cup 500s until its draw includes the club
                print(f"  ({comp_name}: no schedule from ESPN -- {err})")
                continue
            for e in events:
                if e["id"] in seen:
                    continue
                seen.add(e["id"])
                comp_ = e["competitions"][0]
                status = comp_["status"]["type"]
                if status["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                    continue
                us = next(c for c in comp_["competitors"] if c["team"]["id"] == str(team_id))
                them = next(c for c in comp_["competitors"] if c is not us)
                done = bool(status.get("completed"))
                score = lambda c: int(float((c.get("score") or {}).get("value", (c.get("score") or {}).get("displayValue", 0)) or 0)) if done else None
                # a cup tie level after extra time is settled on penalties: the winner flag says who
                result = None
                if done:
                    result = "W" if us.get("winner") else "L" if them.get("winner") else "D"
                start = e["date"] if len(e["date"]) > 17 else e["date"].replace("Z", ":00Z")
                games.append({
                    "id": e["id"],
                    "date": start[:10],
                    "startUTC": start,
                    "tbd": comp_.get("timeValid") is False,
                    "type": 2 if comp == LEAGUE_COMP else 4,      # 4: a cup game, unnumbered
                    "comp": comp_name,
                    "home": us.get("homeAway") == "home",
                    "opp": them["team"].get("abbreviation", ""),
                    "oppName": them["team"].get("shortDisplayName") or them["team"].get("displayName", ""),
                    "oppPlace": "",
                    "ds": score(us),
                    "os": score(them),
                    "result": result,
                    "last": "PK" if done and "pen" in (status.get("detail") or "").lower() else None,
                    "venue": (comp_.get("venue") or {}).get("fullName", ""),
                    "tv": soccer_tv(comp_.get("broadcasts") or []),
                })
    games.sort(key=lambda g: g["startUTC"])
    return games


def soccer_standing(team_id, played):
    """Place in the Premier League and distance to the line that matters, read
    off ESPN's own zone notes: in the relegation places, points from safety
    (the first place above them); elsewhere, points back of the last Champions
    League place, or clear of the first team below it. No one publishes
    playoff-style odds for a league table, so the record fills that slot."""
    data = espn_json(f"https://site.api.espn.com/apis/v2/sports/soccer/{LEAGUE_COMP}/standings")
    entries = data["children"][0]["standings"]["entries"]
    rows = []
    for e in entries:
        st = {s.get("name"): s for s in e.get("stats", []) if s.get("name")}
        num = lambda k: int(float((st.get(k) or {}).get("value") or 0))
        rows.append({"id": e["team"]["id"], "rank": num("rank"), "pts": num("points"), "gp": num("gamesPlayed"),
                     "w": num("wins"), "d": num("ties"), "l": num("losses"),
                     "zone": ((e.get("note") or {}).get("description") or "")})
    rows.sort(key=lambda r: r["rank"])
    us = next(r for r in rows if r["id"] == str(team_id))
    drop = [r for r in rows if "Relegation" in r["zone"]]
    europe = [r for r in rows if "Champions League" in r["zone"]]
    if us in drop:
        safe = rows[rows.index(drop[0]) - 1]
        gap, inside, note = safe["pts"] - us["pts"], False, "from safety"
    elif us in europe:
        first_out = rows[len(europe)]
        gap, inside, note = us["pts"] - first_out["pts"], True, "of fifth place"
    else:
        gap, inside, note = europe[-1]["pts"] - us["pts"], False, "of Champions League"
    current = abs(us["gp"] - played) <= 1
    return {
        "place": us["rank"] if current else None,
        "division": "Premier League",
        "inside": inside,
        "gap": gap if current else None,
        "unit": "Point",
        "gapNote": note,
        "odds": None,
        "record": f"{us['w']}-{us['d']}-{us['l']}",
    }


# ---- College: Michigan in the Big Ten ----------------------------------------

COLLEGE = {"cfb": 5, "cbb": 7}       # ESPN's group id for the Big Ten in each sport
SCHOOLS = {"cfb", "cbb", "chky"}     # college sports: an opponent is just its school


def college_standing(league, team_id, season, played):
    """Place in the Big Ten and games behind first (or, for the leader, games
    clear of second), from ESPN's conference table: its playoffSeed is the
    conference rank, its gamesBehind the distance to first. Football's third
    figure is ESPN FPI's playoff odds (the CFP); basketball has no public odds,
    so its record stands in. ESPN keeps last season's table until games are
    played -- basketball's showed 2025-26 in October -- so a table whose games
    don't match the schedule's shows dashes, like the NBA's."""
    data = espn_json(f"https://site.api.espn.com/apis/v2/sports/{ESPN[league]}/standings?group={COLLEGE[league]}")
    rows = []
    for e in data["standings"]["entries"]:
        st = {x.get("name") or x.get("type"): x for x in e.get("stats", [])}
        disp = lambda k: (st.get(k) or {}).get("displayValue") or ""
        wl = lambda k: [int(n) for n in re.findall(r"\d+", disp(k))[:2]] or [0, 0]
        rows.append({"id": e["team"]["id"], "seed": int(float((st.get("playoffSeed") or {}).get("value") or 99)),
                     "gb": disp("gamesBehind"), "overall": wl("overall"), "conf": wl("vs. Conf."),
                     "overallText": disp("overall")})
    rows.sort(key=lambda r: r["seed"])
    us = next(r for r in rows if r["id"] == str(team_id))
    current = abs(sum(us["overall"]) - played) <= 1
    if us["gb"] in ("-", "", "0"):
        second = next((r for r in rows if r is not us), None)
        gap = ((us["conf"][0] - second["conf"][0]) + (second["conf"][1] - us["conf"][1])) / 2 if second else None
        inside, note = True, "of second place"
    else:
        gap, inside, note = float(us["gb"]), False, "of first place"
    if gap is not None and gap == int(gap):
        gap = int(gap)
    third = None
    odds = None
    if league == "cfb":
        pi = espn_json(f"https://site.web.api.espn.com/apis/fitt/v3/sports/{ESPN[league]}/powerindex")
        if (pi.get("currentSeason") or {}).get("year") == season:
            names = {c["name"]: c["names"] for c in pi.get("categories", [])}
            for t in pi.get("teams", []):
                if t["team"]["id"] == str(team_id):
                    for c in t.get("categories", []):
                        v = dict(zip(names.get(c["name"], []), c.get("values", []))).get("probmakeplayoffs")
                        if isinstance(v, (int, float)):
                            odds = float(v)
    else:
        third = {"big": us["overallText"] if current else "\u2014", "note": "record"}
    return {
        "place": us["seed"] if current else None,
        "division": "Big Ten",
        "inside": inside,
        "gap": gap if current else None,
        "unit": "Game",
        "gapNote": note,
        "odds": odds,
        "third": third,
    }


# ---- College hockey: a Big Ten table worked out from results ----------------

HOCKEY_CORE = "https://sports.core.api.espn.com/v2/sports/hockey/leagues/mens-college-hockey/seasons/%s/types/2/groups"
NPI_URL = "https://ncaa-api.henrygd.me/rankings/icehockey-men/d1/npi"
TOURNAMENT = re.compile(r"quarterfinal|semifinal|final|championship|\bround\b|play-?in|tournament", re.I)


def big_ten_hockey(season):
    """ESPN team ids of the Big Ten's hockey members, kept a week in cache/."""
    path = HERE / "cache" / f"big-ten-hockey-{season}.json"
    if path.exists() and (dt.datetime.now().timestamp() - path.stat().st_mtime) < 7 * 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    for item in espn_json(HOCKEY_CORE % season).get("items", []):
        group = espn_json(item["$ref"].replace("http://", "https://"))
        if "Big Ten" in (group.get("name") or ""):
            teams = espn_json(group["teams"]["$ref"].replace("http://", "https://"))
            ids = [t["$ref"].rsplit("/", 1)[-1].split("?")[0] for t in teams.get("items", [])]
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(ids) + "\n", encoding="utf-8")
            return ids
    return []


def hockey_standing(team_id, season):
    """Michigan's place in the Big Ten, its Big Ten record, and its NPI rank.

    ESPN publishes no college hockey standings at all (the standings app found
    the same), so the table is counted from every member's schedule: completed
    regular-season games between two members, conference tournament games left
    out by their note. Ranked by win percentage, a tie as half a win. The Big
    Ten ranks by points from a system that weights overtime and shootouts,
    which this would only be guessing at -- so the second figure is the Big Ten
    record, not a games-back. NPI decides the NCAA tournament's at-large bids,
    the nearest thing college hockey has to playoff odds; it comes from the
    community ncaa.com mirror the standings app already uses."""
    members = big_ten_hockey(season)
    rec, seen = {m: [0, 0, 0] for m in members}, set()
    for m in members:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{ESPN['chky']}/teams/{m}/schedule?season={season}&seasontype=2"
        for e in espn_json(url).get("events", []):
            comp = e["competitions"][0]
            if e["id"] in seen or not comp["status"]["type"].get("completed"):
                continue
            seen.add(e["id"])
            if any(TOURNAMENT.search(n.get("headline") or "") for n in comp.get("notes", [])):
                continue
            sides = comp["competitors"]
            ids = [x["team"]["id"] for x in sides]
            if len(sides) != 2 or not all(i in rec for i in ids):
                continue
            score = lambda x: int(float((x.get("score") or {}).get("value", 0)))
            for me, them in ((sides[0], sides[1]), (sides[1], sides[0])):
                slot = 0 if score(me) > score(them) else 1 if score(me) < score(them) else 2
                rec[me["team"]["id"]][slot] += 1
    pct = lambda r: (r[0] + r[2] / 2) / sum(r) if sum(r) else 0
    us = rec.get(str(team_id), [0, 0, 0])
    place = 1 + sum(1 for r in rec.values() if pct(r) > pct(us)) if sum(us) else None
    npi = None
    try:
        data = json.loads(fetch(NPI_URL))
        if data.get("title") == "NPI":
            npi = next((int(r["Rank"]) for r in data.get("data", []) if r.get("School") == "Michigan"), None)
    except Exception as err:
        print(f"  ! NPI unavailable ({err})")
    return {
        "place": place,
        "division": "Big Ten",
        "inside": False,
        "gap": None,
        "unit": "Game",
        "odds": None,
        "second": {"big": "%d-%d-%d" % tuple(us) if sum(us) else "\u2014", "note": "Big Ten record"},
        "third": {"big": f"#{npi}" if npi else "\u2014", "note": "NPI rank"},
    }


# ---- seasons ---------------------------------------------------------------

def season_for(league, today):
    """(first day of stories to keep, season id the schedule APIs want).

    A season's stories start with its offseason: July 1 for hockey,
    basketball and soccer (free agency, the summer window), March 1 for
    football (the new league year), November 1 for baseball (after the World
    Series)."""
    y, m = today.year, today.month
    if league in ("nhl", "nba", "epl", "soccer"):
        start = y if m >= 7 else y - 1
        season = int(f"{start}{start + 1}") if league == "nhl" else start + 1 if league == "nba" else start
        return f"{start}-07-01", season
    if league == "nfl":
        start = y if m >= 3 else y - 1
        return f"{start}-03-01", start
    if league == "cfb":                 # from signing day; ESPN names the season by its fall
        start = y if m >= 2 else y - 1
        return f"{start}-02-01", start
    if league == "chky":                # from August; ESPN names the season by its spring
        start = y if m >= 8 else y - 1
        return f"{start}-08-01", start + 1
    if league == "cbb":                 # from the transfer portal; ESPN names it by its spring
        start = y if m >= 4 else y - 1
        return f"{start}-04-01", start + 1
    season = y + 1 if m >= 11 else y
    return f"{season - 1}-11-01", season


def story_tab(feed, rules):
    """A tab of stories only -- no schedule, no table. Its sources are other
    feeds, each labelled; an `include` list keeps only stories whose headline
    has one of its phrases (the Power Rankings tab reads the four team feeds
    for "power rankings"). `allRules: false` exempts a tab from the "All"
    rows of the Sheet, which would otherwise hide exactly what it collects."""
    articles = gather(feed["sources"], "soccer", [w.lower() for w in feed.get("include", [])])
    kept = [a for a in articles if not hidden(a, feed["short"], rules, feed.get("allRules", True))]
    kept.sort(key=lambda a: a["iso"])
    return kept, len(articles) - len(kept)


def main():
    template = (HERE / "template.html").read_text(encoding="utf-8")
    out = HERE / "docs"
    out.mkdir(exist_ok=True)

    # One page, a tab per feed, in config order.
    feeds = []
    rules = read_rules()
    # names first: MGoBlog's posts are sorted while the Football section is gathered
    bb_feed = next((f for f in CONFIG["feeds"] if f.get("league") == "cbb"), None)
    titles = []
    if bb_feed:
        for src in bb_feed["sources"]:
            if src["label"] == "MGoBlog":
                continue
            try:
                since, _ = season_for("cbb", dt.date.today())
                got = read_wordpress(src["feed"], since) if src.get("type") == "wordpress" else read_feed(src["feed"], since)
                titles += [a["title"] for a in got]
            except Exception as err:
                print(f"  ! names: {src['label']} unreadable ({err})")
    fb_feed = next((f for f in CONFIG["feeds"] if f.get("league") == "cfb"), None)
    fb_titles = []
    for src in (fb_feed or {}).get("sources", []):
        if src["label"] == "MGoBlog":
            continue
        try:
            fb_titles += [a["title"] for a in read_feed(src["feed"], season_for("cfb", dt.date.today())[0])]
        except Exception as err:
            print(f"  ! names: {src['label']} unreadable ({err})")
    load_names(titles, fb_titles)
    for feed in CONFIG["feeds"]:
        if feed.get("kind") == "stories":
            articles, dropped = story_tab(feed, rules)
            feeds.append({k: feed[k] for k in ("slug", "short")}
                         | {"league": "stories", "articles": articles, "games": [], "standing": None})
            print(f"{feed['short']}: {len(articles)} stories ({dropped} hidden by rules)")
            continue
        league, team, local_tv = feed["league"], feed["team"], feed.get("localTv", "")
        since, season = season_for(league, dt.date.today())
        if "sources" in feed:
            articles = gather(feed["sources"], league)
        else:
            articles = [{k: v for k, v in a.items() if k != "_text"} for a in read_feed(feed["feed"], since)]
        kept = [a for a in articles if not hidden(a, feed["short"], rules)]
        kept.sort(key=lambda a: a["iso"])
        dropped, articles = len(articles) - len(kept), kept
        if league == "nhl":
            games = nhl_schedule(team, season, local_tv)
        elif league == "epl":
            games = soccer_schedule(team, season)
        elif league in COLLEGE or league == "chky":
            games = espn_schedule(league, team, season, local_tv)
        else:
            games = espn_schedule(league, team, season, local_tv)
        played = len([g for g in games if g["ds"] is not None and g["type"] == 2])
        if league == "nhl":
            standing = nhl_standing(team, played)
        elif league == "epl":
            standing = soccer_standing(team, played)
        elif league in COLLEGE:
            standing = college_standing(league, team, season, played)
        elif league == "chky":
            standing = hockey_standing(team, season)
        else:
            standing = espn_standing(league, team, season, played)
        feeds.append({k: feed[k] for k in ("slug", "short", "league")}
                     | {"articles": articles, "games": games, "standing": standing})
        print(
            f"{feed['short']}: {len(articles)} stories since {since} ({dropped} hidden by rules), "
            f"{played} of {len([g for g in games if g['type'] == 2])} games played\n  {standing}"
        )
    data = json.dumps(
        {"sync": CONFIG.get("sync", ""), "feeds": feeds},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")        # a headline can't close the <script> it sits in
    (out / "index.html").write_text(template.replace("{{DATA}}", data), encoding="utf-8")
    print("-> docs/index.html")


if __name__ == "__main__":
    main()
