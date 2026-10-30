"""Build the site: beat-writer feeds read against each team's schedule.

Reads every feed in config.json, drops what Kyle's rules Sheet hides, adds each
team's games (NHL API, ESPN) and writes docs/index.html from template.html.
README.md has the how and why.

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
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "rss-feeds build (github.com/kyeill/rss-feeds)"}


FETCHED = {}


def fetch(url):
    """One retry after a timeout, a dropped connection or a server error (5xx):
    the build runs hourly, and one slow answer shouldn't fail it
    (and email Kyle). A 403 or 404 is an answer, not a hiccup, and isn't
    retried. Each address is asked once per build, a failure included: the
    names step reads the Michigan feeds before their sections do, and a feed
    that is down shouldn't be waited on twice."""
    if url not in FETCHED:
        try:
            FETCHED[url] = _download(url)
        except Exception as err:
            FETCHED[url] = err
    if isinstance(FETCHED[url], Exception):
        raise FETCHED[url]
    return FETCHED[url]


def _download(url):
    req = urllib.request.Request(url, headers=UA)
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            if err.code < 500 or attempt == 2:
                raise
            time.sleep(5)
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

RULES_HEADER = ["Team", "Look in", "Hide if it contains", "Unless it contains"]
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


def load_names(basketball_titles, football_titles):
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
    """A feed that holds only its newest few posts (MGoBlog keeps 10) would lose
    a story off the page within days, so its posts are kept in cache/archive/,
    one file per feed, and every build adds what's new. A post's sport is saved
    with it, because the full text it is judged on isn't."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE / (re.sub(r"\W+", "-", src["feed"].split("//", 1)[1]).strip("-") + ".json")
    kept = {a["id"]: a for a in (json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])}
    for a in items:
        kept[a["id"]] = {k: v for k, v in a.items() if k != "_text"} | {"sport": sport_of(a["title"], a["_text"])}
    cutoff = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    out = sorted((a for a in kept.values() if a["iso"] >= cutoff), key=lambda a: a["iso"])[-800:]
    path.write_text(json.dumps(out, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    return out


PREVIOUS = {}
STALE = {}      # slug -> labels of feeds that didn't load this run


def previous(slug, label=None):
    """The stories the last published page had for this tab (from one source,
    if a label is given): what a feed that is down this hour is replaced with.
    The Athletic's feeds answered 504 for four hours on 2026-10-28, which
    stopped every build -- and a section with several sources would otherwise
    have gone out missing that source's stories. They were already through
    the Sheet's rules, which run over them again anyway."""
    if not PREVIOUS:
        PREVIOUS[None] = {}
        try:
            page = (HERE / "docs" / "index.html").read_text(encoding="utf-8")
            raw = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1)
            data = json.loads(raw)          # the page escapes </ as <\/, which JSON reads as </
            PREVIOUS[None] = {f["slug"]: f.get("articles", []) for f in data["feeds"]}
        except Exception as err:
            print(f"  ! last page unreadable ({err}); nothing to fall back on")
    arts = PREVIOUS[None].get(slug, [])
    return [dict(a) for a in arts if label is None or a.get("src") == label]


def read_source(src, since):
    return read_wordpress(src["feed"], since) if src.get("type") == "wordpress" else read_feed(src["feed"], since)


def gather(feed):
    """A tab's stories from its feeds, newest kept from the season's start, a
    story in two feeds kept once (first source wins). A source with a `label`
    stamps it on its stories. `include` (the source's own, else the tab's) keeps
    only headlines with one of its phrases; `sport` picks MGoBlog's posts for
    the tab; `palette` names the tab whose colours its unread dates borrow."""
    seen, articles = set(), []
    for src in feed.get("sources") or [{"feed": feed["feed"]}]:
        since, _ = season_for(src.get("league", feed.get("league")))
        label = src.get("label")
        try:
            items = read_source(src, since)
        except Exception as err:
            # the last page's copy stands in; an archived source has its own
            items = [] if src.get("archive") else [a for a in previous(feed["slug"], label) if a["iso"][:10] >= since]
            print(f"  ! {label or feed['short']} unreadable ({err}); {len(items)} stories kept from the last page")
            STALE.setdefault(feed["slug"], set()).add(label or "The Athletic")
        if src.get("feedly"):
            try:
                items += read_feedly(src["feed"])
            except Exception as err:
                print(f"  ! Feedly's copy of {label} unreadable ({err})")
        words = src.get("include") or feed.get("include")
        if words:
            items = [a for a in items if any(w in a["title"].lower() for w in words)]
        if src.get("archive"):
            items = [a for a in remembered(src, items) if a["iso"][:10] >= since]
        for a in items:
            if a["id"] in seen or (src.get("sport") and a["sport"] != src["sport"]):
                continue
            seen.add(a["id"])
            story = {k: v for k, v in a.items() if k not in ("_text", "sport")}
            if label:
                story["src"] = label
            if src.get("palette"):
                story["pal"] = src["palette"]
            articles.append(story)
    return articles


def read_rules():
    """The rows of Kyle's rules Sheet, or the last good copy.

    The rules are the "RSS" tab of Kyle's link-viewable Google Sheet (`rules` in
    config.json), read as CSV. Its first columns must be RULES_HEADER: a Sheet
    asked for a tab that isn't there answers with another tab, not an error.

    When the Sheet can't be read, the last good copy in cache/ is used and the
    build says so; with no copy at all the build stops rather than publish
    every story unfiltered.
    """
    try:
        sid = re.search(r"/d/([\w-]+)", CONFIG["rules"]).group(1)
        gid = re.search(r"gid=(\d+)", CONFIG["rules"]).group(1)
        rows = list(csv.reader(io.StringIO(fetch(
            f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"))))
        if not rows:
            raise ValueError("the rules tab is empty")
        if [c.strip() for c in rows[0][:4]] != RULES_HEADER:      # any columns after these are Kyle's
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


def hidden(article, feed, rules):
    """Does any rule hide this story? A rule applies when its Team is this
    tab (its name, or an older name in its "aka" list -- "Tigers" still finds
    "Detroit Tigers"), All (unless the tab sets `allRules: false`), or the
    story's own source label ("USMNT", "Atlanta"). Matching ignores case and finds the words anywhere, so "NFL" also catches "NFL's".
    A "*" in "Hide if it contains" matches every story, which turns that
    row's "Unless" list into a keep-only list. A story survives only if no
    row hides it, so two keep-only rows for one source must both be met."""
    names = {n.lower() for n in [feed["short"], *feed.get("aka", []), article.get("src") or ""]} - {""}
    if feed.get("allRules", True):
        names.add("all")
    for rule in rules:
        if rule["team"].lower() not in names:
            continue
        text = (article["title"] + (" " + article["dek"] if rule["teaser"] else "")).lower()
        if any(w == "*" or w in text for w in rule["hide"]) and not any(w in text for w in rule["unless"]):
            return True
    return False


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
                "date": g["gameDate"],
                "startUTC": g.get("startTimeUTC"),
                "type": g["gameType"],          # 1 preseason, 2 regular, 3 playoffs
                "home": home,
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


# ---- Everything else: ESPN -------------------------------------------------

ESPN = {"mlb": "baseball/mlb", "nfl": "football/nfl", "nba": "basketball/nba",
        "cfb": "football/college-football", "cbb": "basketball/mens-college-basketball",
        "chky": "hockey/mens-college-hockey"}
SCHOOLS = {"cfb", "cbb", "chky"}     # college sports: an opponent is just its school

# "National" in ESPN's listing but not the channel to watch: out-of-market
# packages, and cable channels whose games the local carrier shows too.
NOT_NATIONAL = {"MLB.TV", "MLBN", "MLB Network", "NBA TV", "NBA League Pass", "NFL+"}


def espn_json(url):
    return json.loads(fetch(url))


def media_name(broadcast):
    return (broadcast.get("media") or {}).get("shortName") or ""


def espn_start(event):
    """ESPN drops the seconds when they are zero: "2026-10-30T23:00Z"."""
    d = event["date"]
    return d if len(d) > 17 else d.replace("Z", ":00Z")


def espn_tv(broadcasts, home, local_tv):
    """One network: a national broadcast if there is one (TV before
    streaming), else this team's own local listing, else its usual local
    channel from config (ESPN lists none for most Pistons and Cavaliers games)."""
    national = sorted(
        (b for b in broadcasts if (b.get("market") or {}).get("type") == "National"
         and media_name(b) and media_name(b) not in NOT_NATIONAL),
        key=lambda b: (b.get("type") or {}).get("shortName") != "TV",
    )
    ours = [b for b in broadcasts if (b.get("market") or {}).get("type") == ("Home" if home else "Away") and media_name(b)]
    return media_name(national[0]) if national else media_name(ours[0]) if ours else local_tv


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
            start = espn_start(e)
            home = us.get("homeAway") == "home"
            games.append({
                "date": start[:10],
                "startUTC": start,
                "tbd": comp.get("timeValid") is False,
                "type": seasontype,
                "home": home,
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


# ---- Soccer: ESPN, one competition at a time ------------------------------

# Every competition a club can play in a season. ESPN's soccer schedules are
# per competition, and one the club isn't in answers with nothing (or, for
# the FA Cup before January, a 500) -- both mean "no games here".
SOCCER_COMPS = [("eng.1", "Premier League"), ("eng.league_cup", "League Cup"), ("eng.fa", "FA Cup"),
                ("uefa.champions", "Champions League"), ("uefa.europa", "Europa League"),
                ("uefa.europa.conf", "Conference League")]

# ESPN lists the Spanish-language channels alongside; Kyle watches in English.
SPANISH = {"Universo", "Telemundo", "UniMás", "UniMas", "TUDN", "ESPN Deportes", "Peacock (Spanish)"}
TV_NAMES = {"USA Net": "USA Network"}


def soccer_tv(broadcasts):
    """One channel: English TV first (NBC, USA), else English streaming (Peacock)."""
    english = [media_name(b) for b in sorted(broadcasts, key=lambda b: (b.get("type") or {}).get("shortName") != "TV")
               if media_name(b) and media_name(b) not in SPANISH]
    return TV_NAMES.get(english[0], english[0]) if english else ""


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
                start = espn_start(e)
                games.append({
                    "date": start[:10],
                    "startUTC": start,
                    "tbd": comp_.get("timeValid") is False,
                    "type": 2 if comp == "eng.1" else 4,      # 4: a cup game, unnumbered
                    "comp": comp_name,
                    "home": us.get("homeAway") == "home",
                    "oppName": them["team"].get("displayName") or them["team"].get("shortDisplayName", ""),
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


# ---- seasons ---------------------------------------------------------------

def season_for(league):
    """(first day of stories to keep, season id the schedule APIs want).

    A season's stories start with its offseason: July 1 for hockey,
    basketball and soccer (free agency, the summer window), March 1 for
    football (the new league year), November 1 for baseball (after the World
    Series)."""
    today = dt.date.today()
    y, m = today.year, today.month
    if league in ("nhl", "nba", "epl"):
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


def headlines(league):
    """The headlines of a Michigan tab's other sources, for load_names."""
    feed = next(f for f in CONFIG["feeds"] if f.get("league") == league)
    titles = []
    for src in feed["sources"]:
        if src["label"] == "MGoBlog":
            continue
        try:
            titles += [a["title"] for a in read_source(src, season_for(league)[0])]
        except Exception as err:
            titles += [a["title"] for a in previous(feed["slug"], src["label"])]
            print(f"  ! names: {src['label']} unreadable ({err}); using the last page's headlines")
    return titles


def schedule(feed):
    if "team" not in feed:              # a story-only tab
        return []
    league, team, local_tv = feed["league"], feed["team"], feed.get("localTv", "")
    season = season_for(league)[1]
    if league == "nhl":
        return nhl_schedule(team, season, local_tv)
    if league == "epl":
        return soccer_schedule(team, season)
    return espn_schedule(league, team, season, local_tv)


def on_page(games):
    """What the page shows of a season: finished games, without venue and TV,
    and the next game in full."""
    upcoming = next((g for g in games if g["ds"] is None), None)
    return [g if g is upcoming else {k: v for k, v in g.items() if k not in ("venue", "tv")}
            for g in games if g["ds"] is not None or g is upcoming]


def main():
    rules = read_rules()
    # names first: MGoBlog's posts are sorted while Michigan Football is gathered
    load_names(headlines("cbb"), headlines("cfb"))
    feeds = []
    for feed in CONFIG["feeds"]:
        articles = gather(feed)
        kept = sorted((a for a in articles if not hidden(a, feed, rules)), key=lambda a: a["iso"])
        games = schedule(feed)
        feeds.append({"slug": feed["slug"], "short": feed["short"], "league": feed.get("league"),
                      "articles": kept, "games": on_page(games), "stale": sorted(STALE.get(feed["slug"], []))})
        played = len([g for g in games if g["ds"] is not None and g["type"] == 2])
        print(f"{feed['short']}: {len(kept)} stories ({len(articles) - len(kept)} hidden by rules), "
              f"{played} of {len([g for g in games if g['type'] == 2])} games played")
    data = json.dumps({"sync": CONFIG["sync"], "feeds": feeds}, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")      # a headline can't close the <script> it sits in
    template = (HERE / "template.html").read_text(encoding="utf-8")
    (HERE / "docs" / "index.html").write_text(template.replace("{{DATA}}", data), encoding="utf-8")
    print("-> docs/index.html")


if __name__ == "__main__":
    main()
