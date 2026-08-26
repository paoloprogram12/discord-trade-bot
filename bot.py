import os
import datetime

import discord
from discord.ext import tasks, commands
from dotenv import load_dotenv
import pytz

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

# Holiday dates when each exchange is fully closed, keyed by session name.
# These need to be updated once a year (dates are published well in advance
# by each exchange). Approximate for London/Asia; exact for NYSE/CME hours,
# since that's the one most futures traders care most about.
HOLIDAYS = {
    "New York": {
        datetime.date(2026, 1, 1),   # New Year's Day
        datetime.date(2026, 1, 19),  # MLK Day
        datetime.date(2026, 2, 16),  # Presidents' Day
        datetime.date(2026, 4, 3),   # Good Friday
        datetime.date(2026, 5, 25),  # Memorial Day
        datetime.date(2026, 6, 19),  # Juneteenth
        datetime.date(2026, 7, 3),   # Independence Day (observed)
        datetime.date(2026, 9, 7),   # Labor Day
        datetime.date(2026, 11, 26), # Thanksgiving
        datetime.date(2026, 12, 25), # Christmas
    },
    "London": {
        datetime.date(2026, 1, 1),   # New Year's Day
        datetime.date(2026, 4, 3),   # Good Friday
        datetime.date(2026, 4, 6),   # Easter Monday
        datetime.date(2026, 5, 4),   # Early May Bank Holiday
        datetime.date(2026, 5, 25),  # Spring Bank Holiday
        datetime.date(2026, 8, 31),  # Summer Bank Holiday
        datetime.date(2026, 12, 25), # Christmas
        datetime.date(2026, 12, 28), # Boxing Day (observed)
    },
    "Asia": {
        datetime.date(2026, 1, 1),   # New Year's Day
        datetime.date(2026, 1, 2),   # New Year's Day (observed)
        datetime.date(2026, 2, 11),  # National Foundation Day
        datetime.date(2026, 3, 20),  # Vernal Equinox
        datetime.date(2026, 4, 29),  # Showa Day
        datetime.date(2026, 5, 4),   # Greenery Day
        datetime.date(2026, 5, 5),   # Children's Day
        datetime.date(2026, 5, 6),   # Constitution Day (observed)
        datetime.date(2026, 7, 20),  # Marine Day
        datetime.date(2026, 8, 11),  # Mountain Day
        datetime.date(2026, 9, 21),  # Respect for the Aged Day
        datetime.date(2026, 9, 22),  # Autumnal Equinox
        datetime.date(2026, 10, 12), # Health and Sports Day
        datetime.date(2026, 11, 3),  # Culture Day
        datetime.date(2026, 11, 23), # Labor Thanksgiving Day
        datetime.date(2026, 12, 23), # Emperor's Birthday
    },
}

def is_holiday(name: str, today: datetime.date) -> bool:
    return today in HOLIDAYS.get(name, set())

# Tracks last date we pinged for each session/event, keyed by "SessionName-open" / "SessionName-close",
# so we don't double-send if the loop ticks more than once inside the same minute.
last_ping_date = {}


def is_weekday(local_dt: datetime.datetime) -> bool:
    # Monday = 0 ... Sunday = 6
    return local_dt.weekday() < 5

@bot.command(name="test")
async def testping(ctx):
    await ctx.send("@everyone this a test")


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
    if not session_clock.is_running():
        session_clock.start()


bot.run(TOKEN)