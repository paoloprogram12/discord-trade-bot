import os
import datetime

import discord
from discord import app_commands
from discord.ext import tasks, commands
from dotenv import load_dotenv
import pytz
import pandas_market_calendars as mcal
import yfinance as yf

# imports for news alerts
import requests
import xml.etree.ElementTree as ET

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Each session has its own timezone and local open/close time.
# Add or edit entries here to change session hours.
SESSIONS = [
    {
        "name": "Asia",
        "tz": pytz.timezone("Asia/Tokyo"),
        "open": datetime.time(9, 0),
        "close": datetime.time(15, 0),
        "emoji_open": "🌅",
        "emoji_close": "🌙",
    },
    {
        "name": "London",
        "tz": pytz.timezone("Europe/London"),
        "open": datetime.time(8, 0),
        "close": datetime.time(16, 30),
        "emoji_open": "🇬🇧",
        "emoji_close": "🇬🇧",
    },
    {
        "name": "New York",
        "tz": pytz.timezone("US/Eastern"),
        "open": datetime.time(9, 30),
        "close": datetime.time(16, 0),
        "emoji_open": "🗽",
        "emoji_close": "🗽",
    },
]

# --- High-impact news announcements ---
#
# Pulls from the official Fair Economy (ForexFactory's parent company)
# calendar feed. This is the same feed most trading bots/EAs use — it's
# meant for exactly this kind of automated consumption, unlike scraping
# forexfactory.com's own pages directly, which violates their ToS and is
# fragile since the calendar there is rendered by JavaScript anyway.
#
# Caveat: this feed's times reflect whatever timezone the feed defaults
# to (commonly US/Eastern). If pings look off by a few hours compared to
# the live calendar on forexfactory.com, adjust NEWS_FEED_TZ below.
NEWS_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
NEWS_FEED_TZ = pytz.timezone("US/Eastern")
HEADS_UP_MINUTES = 15  # how far ahead of the event to ping


# Maps event -> scheduled datetime, so we know what we've already announced
# and can prune old entries instead of growing forever.
announced_events = {}

# Each session maps to an official exchange calendar, which
# pandas_market_calendars keeps updated with published holiday schedules —
# no manual date maintenance needed.
CALENDARS = {
    "Asia": mcal.get_calendar("JPX"),
    "London": mcal.get_calendar("LSE"),
    "New York": mcal.get_calendar("CME_Equity"),
}

# Cache of holiday dates per session per year, so we don't recompute the
# full valid-trading-days schedule on every loop tick.
_holiday_cache = {}

def is_holiday(name: str, today: datetime.date) -> bool:
    calendar = CALENDARS.get(name)
    if calendar is None:
        return False

    cache_key = (name, today.year)
    if cache_key not in _holiday_cache:
        schedule = calendar.schedule(start_date=f"{today.year}-01-01", end_date=f"{today.year}-12-31")
        trading_days = set(schedule.index.date)
        _holiday_cache[cache_key] = trading_days

    trading_days = _holiday_cache[cache_key]
    # A "holiday" here means: it's not a normal weekend, but the exchange
    # still isn't open (i.e. not in the official trading day list).
    return today not in trading_days

# Tracks last date we pinged for each session/event, keyed by "SessionName-open" / "SessionName-close",
# so we don't double-send if the loop ticks more than once inside the same minute.
last_ping_date = {}

# news alerts
def fetch_high_impact_events():
    response = requests.get(NEWS_FEED_URL, timeout=10)
    response.raise_for_status()
    root = ET.fromstring(response.content)

    events = []
    for event in root.findall("event"):
        impact = (event.findtext("impact") or "").strip()
        if impact != "High":
            continue

        date_str = (event.findtext("date") or "").strip()
        time_str = (event.findtext("time") or "").strip()
        if not date_str or not time_str:
            continue
        if time_str.lower() in ("all day", "tentative", "day 1", "day 2"):
            continue

        try:
            naive_dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
        except ValueError:
            continue

        events.append({
            "title": (event.findtext("title") or "").strip(),
            "country": (event.findtext("country") or "").strip(),
            "forecast": (event.findtext("forecast") or "").strip(),
            "previous": (event.findtext("previous") or "").strip(),
            "datetime": NEWS_FEED_TZ.localize(naive_dt),
        })
    return events

@tasks.loop(minutes=5)
async def news_watcher():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        return

    try:
        events = fetch_high_impact_events()
    except Exception as e:
        print(f"Failed to fetch news calendar: {e}")
        return

    now = datetime.datetime.now(NEWS_FEED_TZ)

    # Prune anything more than a day old so this dict doesn't grow forever
    stale_cutoff = now - datetime.timedelta(days=1)
    for key in [k for k, dt in announced_events.items() if dt < stale_cutoff]:
        del announced_events[key]

    for event in events:
        key = f"{event['title']}|{event['country']}|{event['datetime'].isoformat()}"
        if key in announced_events:
            continue

        minutes_until = (event["datetime"] - now).total_seconds() / 60
        if 0 <= minutes_until <= HEADS_UP_MINUTES:
            details = []
            if event["forecast"]:
                details.append(f"Forecast: {event['forecast']}")
            if event["previous"]:
                details.append(f"Previous: {event['previous']}")
            detail_text = f" ({' | '.join(details)})" if details else ""

            await channel.send(
                f"@everyone 🔴 **High-impact news in ~{int(minutes_until)} min** "
                f"— {event['country']}: {event['title']}{detail_text}"
            )
            announced_events[key] = event["datetime"]


@news_watcher.before_loop
async def before_news_watcher():
    await bot.wait_until_ready()

def is_weekday(local_dt: datetime.datetime) -> bool:
    # Monday = 0 ... Sunday = 6
    return local_dt.weekday() < 5

@bot.command(name="test")
async def testping(ctx):
    await ctx.send("@everyone this a test")

# Maps common shorthand futures tickers to their Yahoo Finance continuous-
# contract symbols. Add more here as group trades new products.
FUTURES_ALIASES = {
    "ES": "ES=F",   # S&P 500 E-mini
    "NQ": "NQ=F",   # Nasdaq 100 E-mini
    "YM": "YM=F",   # Dow E-mini
    "RTY": "RTY=F", # Russell 2000 E-mini
    "CL": "CL=F",   # Crude Oil
    "GC": "GC=F",   # Gold
    "SI": "SI=F",   # Silver
    "NG": "NG=F",   # Natural Gas
    "ZB": "ZB=F",   # 30Y Treasury Bond
    "6E": "6E=F",   # Euro FX
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
}

def resolve_symbol(raw_ticker: str) -> str:
    ticker = raw_ticker.strip().upper()
    return FUTURES_ALIASES.get(ticker, ticker)

@bot.tree.command(name="price", description="Get the latest price for a future ticker (e.g. ES, NQ, CL, GC)")
@app_commands.describe(ticker="Ticker symbol, e.g. ES, NQ, CL, GC, BTC")
async def price(interaction: discord.Interaction, ticker: str):
    await interaction.response.defer()

    symbol = resolve_symbol(ticker)

    try:
        data = yf.Ticker(symbol)
        info = data.fast_info
        last_price = info["lastPrice"]
        prev_close = info["previousClose"]
    except Exception:
        await interaction.followup.send(
            f"Couldn't find price data for `{ticker.upper()}`. Double-check the symbol and try again."
        )
        return

    change = last_price - prev_close
    pct_change = (change / prev_close) * 100 if prev_close else 0
    direction = "🟢" if change >= 0 else "🔴"

    embed = discord.Embed(
        title=f"{ticker.upper()} ({symbol})",
        description=f"{direction} **{last_price:,.2f}**  ({change:+,.2f} / {pct_change:+.2f}%)",
        color=discord.Color.green() if change >= 0 else discord.Color.red(),
    )
    embed.set_footer(text="Data via Yahoo Finance — may be delayed")

    await interaction.followup.send(embed=embed)

@bot.command(name="testnews")
async def testnews(ctx):
    """Shows the next few upcoming high-impact events, regardless of the
    15-minute ping window — lets you verify the feed/parsing works without
    waiting for a real event to be imminent."""
    try:
        events = fetch_high_impact_events()
    except Exception as e:
        await ctx.send(f"Failed to fetch the news calendar: `{e}`")
        return

    now = datetime.datetime.now(NEWS_FEED_TZ)
    upcoming = sorted(
        [e for e in events if e["datetime"] > now],
        key=lambda e: e["datetime"],
    )[:5]

    if not upcoming:
        await ctx.send("No upcoming high-impact events found in this week's feed.")
        return

    lines = ["**Next 5 upcoming high-impact events:**"]
    for event in upcoming:
        minutes_until = int((event["datetime"] - now).total_seconds() / 60)
        hours = minutes_until // 60
        mins = minutes_until % 60
        countdown = f"{hours}h {mins}m" if hours else f"{mins}m"
        lines.append(
            f"🔴 {event['country']}: **{event['title']}** — "
            f"{event['datetime'].strftime('%a %b %d, %I:%M %p %Z')} (in {countdown})"
        )

    await ctx.send("\n".join(lines))


@bot.command(name="forcenews")
async def forcenews(ctx):
    """Sends a real announcement using the next upcoming high-impact event's
    actual data, bypassing the 15-minute window — for testing the exact
    message format that will get sent to @everyone."""
    try:
        events = fetch_high_impact_events()
    except Exception as e:
        await ctx.send(f"Failed to fetch the news calendar: `{e}`")
        return

    now = datetime.datetime.now(NEWS_FEED_TZ)
    upcoming = sorted(
        [e for e in events if e["datetime"] > now],
        key=lambda e: e["datetime"],
    )

    if not upcoming:
        await ctx.send("No upcoming high-impact events to test with.")
        return

    event = upcoming[0]
    minutes_until = int((event["datetime"] - now).total_seconds() / 60)

    details = []
    if event["forecast"]:
        details.append(f"Forecast: {event['forecast']}")
    if event["previous"]:
        details.append(f"Previous: {event['previous']}")
    detail_text = f" ({' | '.join(details)})" if details else ""

    await ctx.send(
        f"[TEST — not a real alert] @everyone 🔴 **High-impact news in ~{minutes_until} min** "
        f"— {event['country']}: {event['title']}{detail_text}"
    )

@tasks.loop(seconds=30)
async def session_clock():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"Couldn't find channel with ID {CHANNEL_ID}")
        return

    for session in SESSIONS:
        local_dt = datetime.datetime.now(session["tz"])
        if not is_weekday(local_dt):
            continue

        today = local_dt.date()

        if is_holiday(session["name"], today):
            continue

        current_time = local_dt.time()
        name = session["name"]

        open_key = f"{name}-open"
        close_key = f"{name}-close"

        # Open ping: fire once, in the minute right after open time
        if current_time >= session["open"] and last_ping_date.get(open_key) != today:
            open_end = (datetime.datetime.combine(today, session["open"]) + datetime.timedelta(minutes=1)).time()
            if current_time < open_end:
                await channel.send(f"@everyone {session['emoji_open']} **{name} session is open.**")
                last_ping_date[open_key] = today

        # Close ping: fire once, in the minute right after close time
        if current_time >= session["close"] and last_ping_date.get(close_key) != today:
            close_end = (datetime.datetime.combine(today, session["close"]) + datetime.timedelta(minutes=1)).time()
            if current_time < close_end:
                await channel.send(f"@everyone {session['emoji_close']} **{name} session is closed.**")
                last_ping_date[close_key] = today


@session_clock.before_loop
async def before_session_clock():
    await bot.wait_until_ready()

GUILD_ID = os.environ.get("GUILD_ID")  # your server's ID, for instant command sync

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
    if not session_clock.is_running():
        session_clock.start()

    if not news_watcher.is_running():
        news_watcher.start()

bot.run(TOKEN)