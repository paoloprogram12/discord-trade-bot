import os
import datetime

import discord
from discord import app_commands
from discord.ext import tasks, commands
from dotenv import load_dotenv
import pytz
import pandas_market_calendars as mcal
import yfinance as yf

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

bot.run(TOKEN)