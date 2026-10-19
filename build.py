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
import io
import json
import html
import hashlib
import re
import pathlib
import datetime as dt
import urllib.request

HERE = pathlib.Path(__file__).parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "rss-feeds build (github.com/kyeill/rss-feeds)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


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
        # RSS dates are RFC 822 and always land in GMT here
        when = dt.datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").replace(
            tzinfo=dt.timezone.utc
        )
        link = tag("link")
        if when.date().isoformat() < since or link in seen:
            continue
        seen.add(link)
        items.append(
            {
                "id": story_id(link),
                "title": tag("title"),
                "dek": tag("description"),
                "link": link,
                "iso": when.isoformat(),
            }
        )
    items.sort(key=lambda a: a["iso"])
    return items


# ---- Kyle's rules: which stories to leave out ---------------------------------

RULES_HEADER = ["Team", "Look in", "Hide if it contains", "Unless it contains", "Notes"]
RULES_CACHE = HERE / "cache" / "rules.json"


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


def hidden(article, team, rules):
    """Does any rule for this team (or All) hide this story? Matching ignores
    case and finds the words anywhere, so "NFL" also catches "NFL's"."""
    for rule in rules:
        if rule["team"].lower() not in ("all", team.lower()):
            continue
        text = (article["title"] + (" " + article["dek"] if rule["teaser"] else "")).lower()
        if any(w in text for w in rule["hide"]) and not any(w in text for w in rule["unless"]):
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

ESPN = {"mlb": "baseball/mlb", "nfl": "football/nfl", "nba": "basketball/nba"}

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
            us = next(c for c in comp["competitors"] if c["team"]["abbreviation"] == abbrev)
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
                "oppName": them["team"].get("name") or them["team"].get("shortDisplayName", ""),
                "oppPlace": them["team"].get("location", ""),
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


# ---- seasons ---------------------------------------------------------------

def season_for(league, today):
    """(first day of stories to keep, season id the schedule APIs want).

    A season's stories start with its offseason: July 1 for hockey and
    basketball (free agency), March 1 for football (the new league year),
    November 1 for baseball (after the World Series)."""
    y, m = today.year, today.month
    if league in ("nhl", "nba"):
        start = y if m >= 7 else y - 1
        return f"{start}-07-01", (int(f"{start}{start + 1}") if league == "nhl" else start + 1)
    if league == "nfl":
        start = y if m >= 3 else y - 1
        return f"{start}-03-01", start
    season = y + 1 if m >= 11 else y
    return f"{season - 1}-11-01", season

def main():
    template = (HERE / "template.html").read_text(encoding="utf-8")
    out = HERE / "docs"
    out.mkdir(exist_ok=True)

    # One page, a tab per feed, in config order.
    feeds = []
    rules = read_rules()
    for feed in CONFIG["feeds"]:
        league, team, local_tv = feed["league"], feed["team"], feed.get("localTv", "")
        since, season = season_for(league, dt.date.today())
        articles = read_feed(feed["feed"], since)
        kept = [a for a in articles if not hidden(a, feed["short"], rules)]
        dropped, articles = len(articles) - len(kept), kept
        if league == "nhl":
            games = nhl_schedule(team, season, local_tv)
        else:
            games = espn_schedule(league, team, season, local_tv)
        played = len([g for g in games if g["ds"] is not None and g["type"] == 2])
        if league == "nhl":
            standing = nhl_standing(team, played)
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
