# life.py
import os
import sqlite3
from datetime import datetime
from threading import Thread
from flask import Flask

import discord
from discord.ext import commands

# ---------------- CONFIG ----------------
TOKEN = os.getenv("TOKEN")
GUILD_ID = None  # replace with your server ID for instant slash command sync
BUTTON_COOLDOWN = 10  # seconds per user per button

DB_PATH = "points.db"

# Points mapping
POINTS = {
    # Punishments (red, negative)
    "open_youtube": -15,
    "open_instagram": -15,
    "video": -5,
    "reel": -10,
    "open_game": -15,
    # Nourishment (green, positive)
    "timetable_chunk": 5,
    "make_grad_video": 15,
    "reconnect_friends": 10,
    # Dare buttons (blue, add points)
    "dare": 50,
    "double_dare": 80,
    # Reset button handled separately
    "reset": 0,
}

# Predefined dare list
DARES = [
    "Eat an apple 🍎",
    "Eat an orange 🍊",
    "Eat a banana 🍌"
]

# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points INTEGER NOT NULL DEFAULT 0,
            last_updated TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_points(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        pts = row[0]
    else:
        pts = 0
        c.execute("INSERT INTO users (user_id, points, last_updated) VALUES (?,?,?)",
                  (user_id, 0, datetime.utcnow().isoformat()))
        conn.commit()
    conn.close()
    return pts

def set_points(user_id: int, points: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, points, last_updated) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET points=excluded.points, last_updated=excluded.last_updated",
        (user_id, points, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

def add_points(user_id: int, delta: int) -> int:
    current = get_points(user_id)
    new = current + delta
    set_points(user_id, new)
    return new

def top_leaderboard(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, points FROM users ORDER BY points DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# ---------------- COOLDOWNS ----------------
_click_timestamps = {}

def is_on_cooldown(user_id: int, key: str):
    last = _click_timestamps.get((user_id, key))
    if last:
        elapsed = (datetime.utcnow() - last).total_seconds()
        if elapsed < BUTTON_COOLDOWN:
            return True, BUTTON_COOLDOWN - elapsed
    return False, 0.0

def set_click_time(user_id: int, key: str):
    _click_timestamps[(user_id, key)] = datetime.utcnow()

# ---------------- BUTTON UI ----------------
class PointButton(discord.ui.Button):
    def __init__(self, label: str, key: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id=f"pointbtn:{key}")
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        on_cd, remaining = is_on_cooldown(user.id, self.key)
        if on_cd:
            await interaction.response.send_message(
                f"You're on cooldown for this action. Try again in {remaining:.1f}s.", ephemeral=False
            )
            return
        set_click_time(user.id, self.key)

        if self.key == "reset":
            set_points(user.id, 0)
            await interaction.response.send_message(f"{user.mention}, your points have been reset to 0.", ephemeral=False)
            return

        delta = POINTS.get(self.key, 0)
        new_total = add_points(user.id, delta)
        sign = "+" if delta >= 0 else ""
        await interaction.response.send_message(
            f"{self.label}: {sign}{delta} points. Your new total is {new_total} points.", ephemeral=False
        )

class PointsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # Red punishment buttons
        self.add_item(PointButton("Open YouTube", "open_youtube", discord.ButtonStyle.danger))
        self.add_item(PointButton("Open Instagram", "open_instagram", discord.ButtonStyle.danger))
        self.add_item(PointButton("Watch Video", "video", discord.ButtonStyle.danger))
        self.add_item(PointButton("Watch Reel", "reel", discord.ButtonStyle.danger))
        self.add_item(PointButton("Open Game", "open_game", discord.ButtonStyle.danger))
        # Blue dare buttons
        self.add_item(PointButton("DARE", "dare", discord.ButtonStyle.primary))
        self.add_item(PointButton("DOUBLE DARE", "double_dare", discord.ButtonStyle.primary))
        # Green nourishment buttons
        self.add_item(PointButton("Timetable chunk", "timetable_chunk", discord.ButtonStyle.success))
        self.add_item(PointButton("Make grad video", "make_grad_video", discord.ButtonStyle.success))
        self.add_item(PointButton("Reconnect with friends", "reconnect_friends", discord.ButtonStyle.success))
        # Reset button (grey/white)
        self.add_item(PointButton("Reset Points", "reset", discord.ButtonStyle.secondary))

class DareView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DareButton())

class DareButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Generate a dare", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        dare = random.choice(DARES)
        await interaction.response.send_message(f"🎲 Your dare: **{dare}**", ephemeral=False)

# Slash command for dare
@bot.tree.command(name="dare", description="Get a random dare")
async def dare(interaction: discord.Interaction):
    view = DareView()
    await interaction.response.send_message(
        "Click the button to generate a random dare!",
        view=view,
        ephemeral=False
    )

# ---------------- BOT SETUP ----------------
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    init_db()
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    try:
        if GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        else:
            await bot.tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print("Could not sync commands:", e)

# ---------------- SLASH COMMANDS ----------------
@bot.tree.command(name="panel", description="Post the interactive points panel")
async def panel(interaction: discord.Interaction):
    view = PointsView()
    embed = discord.Embed(
        title="Focus Points Panel",
        description="Click buttons below to self-report actions.\nPunishments deduct points; nourishment grants points.\nUse `/mypoints` to check your balance.",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="mypoints", description="Check your points")
async def mypoints(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    pts = get_points(member.id)
    await interaction.response.send_message(f"{member.mention} has **{pts} points**.")

@bot.tree.command(name="leaderboard", description="Show top 10 users")
async def leaderboard(interaction: discord.Interaction):
    rows = top_leaderboard(10)
    if not rows:
        await interaction.response.send_message("Leaderboard is empty.")
        return
    desc = []
    for idx, (user_id, pts) in enumerate(rows, start=1):
        user = bot.get_user(user_id)
        name = user.name if user else f"User ID {user_id}"
        desc.append(f"**{idx}.** {name} — {pts} pts")
    await interaction.response.send_message("\n".join(desc))

@bot.tree.command(name="reset_points", description="Reset points for a user or yourself (admins can reset anyone)")
async def reset_points(interaction: discord.Interaction, member: discord.Member = None):
    if member:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only admins can reset other users' points.", ephemeral=False)
            return
        set_points(member.id, 0)
        await interaction.response.send_message(f"{member.mention}'s points have been reset to 0.")
    else:
        set_points(interaction.user.id, 0)
        await interaction.response.send_message(f"{interaction.user.mention}, your points have been reset to 0.")

# ---------------- RUN BOT ----------------
if __name__ == "__main__":
    init_db()

    # Optional keep-alive web server for Render / Railway
    app = Flask('')

    @app.route('/')
    def home():
        return "Bot is alive!"

    def run_web():
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port)

    Thread(target=run_web).start()

    bot.run(TOKEN)



