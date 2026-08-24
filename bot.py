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

