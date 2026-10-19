"""Build the site: an RSS feed read against the team's schedule.

Sources, all public:

  * the feed itself (siftrss in front of The Athletic, which does not hand out
    its own RSS any more) -- a few dozen items, always the newest ones;
  * the NHL's public schedule endpoint, one call per season, and its standings;
  * Hockey-Reference's playoff probabilities, at most twice a day (cache/).

Every run re-asks the NHL and the feed and rewrites docs/index.html from
template.html.

    python build.py
"""

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


def season_of(today):
    """The NHL season id for a date: 2026-10-18 and 2027-03-01 are both 20262027."""
    y = today.year if today.month >= 7 else today.year - 1
    return y, int(f"{y}{y + 1}")


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


def read_standing(abbrev):
    """Where the club stands: division place, and how far it is from the
    playoff line. A conference sends the top three of each division plus two
    wild cards, so a team outside is as far back as the NEARER of its
    division's third place and the conference's second wild card; a team
    inside is as far clear as it is above the conference's first team out."""
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
    return {
        "place": us["divisionSequence"],
        "division": us["divisionName"],
        "inside": inside(us),
        "gap": gap,
        "points": us["points"],
        "name": us["teamName"]["default"],
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


def pick_tv(broadcasts, local_tv):
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


def read_schedule(abbrev, season, local_tv):
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
                "tv": pick_tv(g.get("tvBroadcasts", []), local_tv),
            }
        )
    games.sort(key=lambda g: g["startUTC"] or g["date"])
    return games


def main():
    today = dt.date.today()
    start_year, season = season_of(today)
    # The feed carries older items than the page wants; a season starts in July.
    since = f"{start_year}-07-01"

    template = (HERE / "template.html").read_text(encoding="utf-8")
    out = HERE / "docs"
    out.mkdir(exist_ok=True)

    # One page, a tab per feed.
    feeds = []
    for feed in CONFIG["feeds"]:
        articles = read_feed(feed["feed"], since)
        games = read_schedule(feed["nhl"], season, feed.get("localTv", ""))
        standing = read_standing(feed["nhl"])
        standing["odds"] = read_odds(standing["name"], standing["points"])
        print(f"  {standing}")
        feeds.append({k: feed[k] for k in ("slug", "short", "source")}
                     | {"articles": articles, "games": games, "standing": standing})
        played = [g for g in games if g["ds"] is not None and g["type"] == 2]
        print(
            f"{feed['short']}: {len(articles)} stories since {since}, "
            f"{len(played)} of {len([g for g in games if g['type'] == 2])} games played"
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
