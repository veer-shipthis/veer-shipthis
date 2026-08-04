import datetime
import json
import os
import time
import urllib.request

LOGIN = os.environ.get("STREAK_LOGIN", "veer-shipthis")
TOKEN = os.environ["STREAK_TOKEN"]
OUT = os.environ.get("STREAK_OUT", "assets/weekday-streak.svg")

BG = "#1A1B27"
BLUE = "#70A5FD"
TEAL = "#38BDAE"
PURPLE = "#BF91F3"
WHITE = "#FFFFFF"
FONT = "'Segoe UI', Ubuntu, sans-serif"


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise SystemExit(json.dumps(payload["errors"])[:800])
    return payload["data"]


YEARS = """
query($login:String!){ user(login:$login){ contributionsCollection{ contributionYears } } }
"""

CALENDAR = """
query($login:String!, $from:DateTime!, $to:DateTime!){
  user(login:$login){
    contributionsCollection(from:$from, to:$to){
      contributionCalendar{ weeks{ contributionDays{ date contributionCount weekday } } }
    }
  }
}
"""


def fetch_once():
    years = graphql(YEARS, {"login": LOGIN})["user"]["contributionsCollection"]["contributionYears"]
    days = {}
    for year in sorted(years):
        data = graphql(CALENDAR, {"login": LOGIN, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"})
        for week in data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = (day["contributionCount"], day["weekday"])
    return days


def fetch_days():
    # Replicas occasionally serve stale calendars that under-report a day to zero and
    # falsely break the streak, so take the highest count each date reports across reads.
    # Consecutive requests tend to hit the same replica, hence the gap between them.
    merged = {}
    for attempt in range(4):
        if attempt:
            time.sleep(6)
        for date, (count, weekday) in fetch_once().items():
            if count >= merged.get(date, (0, weekday))[0]:
                merged[date] = (count, weekday)
    return merged


def compute(days):
    today = datetime.date.today()
    weekdays = sorted((d, c) for d, (c, wd) in days.items() if wd not in (0, 6) and datetime.date.fromisoformat(d) <= today)

    longest = current_run = 0
    longest_range = run_start = None
    for date, count in weekdays:
        if count:
            if not current_run:
                run_start = date
            current_run += 1
            if current_run > longest:
                longest, longest_range = current_run, (run_start, date)
        else:
            current_run = 0

    # An empty final weekday is still in progress, so it must not break the streak.
    current = 0
    current_start = current_end = None
    for date, count in reversed(weekdays):
        if count:
            current += 1
            current_start = date
            if not current_end:
                current_end = date
        elif current or date != weekdays[-1][0]:
            break

    return {
        "active": sum(1 for _, c in weekdays if c),
        "current": current,
        "current_range": (current_start, current_end),
        "longest": longest,
        "longest_range": longest_range,
    }


def fmt(date):
    return datetime.date.fromisoformat(date).strftime("%b %-d, %Y") if date else "—"


def fmt_range(pair):
    if not pair or not pair[0]:
        return "—"
    start, end = pair
    return f"{fmt(start)} - {fmt(end)}" if start != end else fmt(start)


def text(x, y, value, fill, size, weight="400"):
    return (
        f"<text x='{x}' y='{y}' text-anchor='middle' fill='{fill}' "
        f"font-family=\"{FONT}\" font-size='{size}px' font-weight='{weight}'>{value}</text>"
    )


def render(stats):
    cols = [
        (110, f"{stats['active']:,}", "Active Weekdays", "Mon-Fri with commits"),
        (280, str(stats["current"]), "Current Weekday Streak", fmt_range(stats["current_range"])),
        (450, str(stats["longest"]), "Longest Weekday Streak", fmt_range(stats["longest_range"])),
    ]
    parts = [
        "<svg xmlns='http://www.w3.org/2000/svg' width='560' height='200' viewBox='0 0 560 200'>",
        f"<rect width='560' height='200' rx='6' fill='{BG}'/>",
        f"<line x1='195' y1='45' x2='195' y2='155' stroke='{WHITE}' stroke-opacity='0.35'/>",
        f"<line x1='365' y1='45' x2='365' y2='155' stroke='{WHITE}' stroke-opacity='0.35'/>",
        f"<circle cx='280' cy='88' r='42' fill='none' stroke='{BLUE}' stroke-width='4'/>",
    ]
    for x, value, label, sub in cols:
        colour = PURPLE if x == 280 else BLUE
        parts.append(text(x, 98, value, WHITE if x == 280 else colour, 34 if x != 280 else 30, "700"))
        parts.append(text(x, 140, label, colour, 13, "600"))
        parts.append(text(x, 160, sub, TEAL, 11))
    parts.append(text(280, 186, "* Weekends excluded from streaks", TEAL, 10))
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    stats = compute(fetch_days())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(render(stats))
    print(json.dumps({k: str(v) for k, v in stats.items()}, indent=2))


if __name__ == "__main__":
    main()
