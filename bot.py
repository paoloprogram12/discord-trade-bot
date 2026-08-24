import os
import datetime

import discord
from discord.ext import tasks, commands
from dotenv import load_dotenv
import pytz

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])

EASTERN = pytz.timezone("US/Eastern")
MARKET_OPEN = datetime.time(9, 30)
MARKET_CLOSE = datetime.time(16, 0)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Tracks the last date we sent an open/close ping, so we don't double-send
# if the loop happens to tick more than once inside the same minute.
last_open_ping_date = None
last_close_ping_date = None

def is_weekday(now_eastern: datetime.datetime) -> bool:
    # Monday = 0 ... Sunday = 6
    return now_eastern.weekday() < 5

@tasks.loop(seconds=30)
async def market_clock():
    global last_open_ping_date, last_close_ping_date

    now_eastern = datetime.datetime.now(EASTERN)
    today = now_eastern.date()
    current_time = now_eastern.time()

    if not is_weekday(now_eastern):
        return

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"Couldn't find channel with ID {CHANNEL_ID}")
        return

    # Market open: fire once, right at/after 9:30
    if current_time >= MARKET_OPEN and last_open_ping_date != today:
        if current_time < datetime.time(9, 31):  # narrow window so a bot restart doesn't spam-fire hours later
            await channel.send("@everyone 🔔 **Market is open.** Get to trading.")
            last_open_ping_date = today

    # Market close: fire once, right at/after 16:00
    if current_time >= MARKET_CLOSE and last_close_ping_date != today:
        if current_time < datetime.time(16, 1):
            await channel.send("@everyone 🔒 **Market is closed.** Geeg.")
            last_close_ping_date = today

@market_clock.before_loop
async def before_market_clock():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not market_clock.is_running():
        market_clock.start()


bot.run(TOKEN)