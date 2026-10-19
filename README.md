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
| `config.json` | the feeds: name, source, NHL club, feed URL |
| `build.py` | reads each feed and that club's season, writes `docs/` |
| `template.html` | the whole page — CSS and the script that lays out the timeline |
| `docs/index.html` | the built page, committed, served by Pages from `main` |

```bash
python build.py
```

No dependencies; standard library only. GitHub Actions runs the same command
every three hours and commits `docs/` when the feed has moved.

## How a story finds its place

Every story is anchored to the last game that started before it was filed, and
tagged by how long after:

| tag | when |
| --- | --- |
| **Same night** | within 6 hours of puck drop |
| **Next morning** | 6 to 26 hours after |
| **Gameday** | filed on the day of a game, before it starts |
| *(none)* | an off day — the gap says how many days |

Games carry the record as it stood after them, so the standings move down the
page with the stories. Preseason games show as `PS` and change no record.

## Traps already paid for

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
