# bot.py
import os
import sqlite3
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ---------- CONFIG ----------
TOKEN = os.getenv("DISCORD_TOKEN") or "PASTE_YOUR_TOKEN_HERE"
GUILD_ID = None  # Optional: set your guild id to register commands to one guild quickly, else None

# cooldown seconds per user per button
BUTTON_COOLDOWN = 10

# Points mapping (you can edit these)
POINTS = {
    # punishments (negative)
    "open_youtube": -15,
    "open_instagram": -15,
    "video": -5,
    "reel": -10,
    "open_game": -15,
    "dare": -50,
    "double_dare": -80,
    # nourishment (positive)
    "timetable_chunk": +5,
    "make_grad_video": +15,
    "reconnect_friends": +10,
}

DB_PATH = "points.db"
# ----------------------------

intents = discord.Intents.default()
intents.messages = True
intents.message_content = False  # not required for buttons/actions
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Database helpers ---
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
    c.execute("INSERT INTO users (user_id, points, last_updated) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET points=excluded.points, last_updated=excluded.last_updated",
              (user_id, points, datetime.utcnow().isoformat()))
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

# --- Simple per-user cooldown tracker ---
# maps (user_id, action_key) -> datetime of last click
_click_timestamps = {}

def is_on_cooldown(user_id: int, action_key: str) -> (bool, float):
    key = (user_id, action_key)
    last = _click_timestamps.get(key)
    if last:
        elapsed = (datetime.utcnow() - last).total_seconds()
        if elapsed < BUTTON_COOLDOWN:
            return True, BUTTON_COOLDOWN - elapsed
    return False, 0.0

def set_click_time(user_id: int, action_key: str):
    key = (user_id, action_key)
    _click_timestamps[key] = datetime.utcnow()

# --- UI: build a View with buttons ---
class PointButton(discord.ui.Button):
    def __init__(self, label: str, key: str, style: discord.ButtonStyle = discord.ButtonStyle.primary):
        super().__init__(label=label, style=style, custom_id=f"pointbtn:{key}")
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        # cooldown
        on_cd, remaining = is_on_cooldown(user.id, self.key)
        if on_cd:
            await interaction.response.send_message(
                f"You're on cooldown for this action. Try again in {remaining:.1f}s.", ephemeral=True
            )
            return

        set_click_time(user.id, self.key)

        delta = POINTS.get(self.key, 0)
        new_total = add_points(user.id, delta)

        # ephemeral confirm
        sign = "+" if delta >= 0 else ""
        action_name = self.label
        await interaction.response.send_message(
            f"{action_name}: {sign}{delta} points. Your new total is {new_total} points.", ephemeral=True
        )

class PointsView(discord.ui.View):
    def __init__(self, timeout: int = None):
        super().__init__(timeout=timeout)
        # Punishment buttons (negative)
        self.add_item(PointButton("Open YouTube (punishment)", "open_youtube", discord.ButtonStyle.danger))
        self.add_item(PointButton("Open Instagram (punishment)", "open_instagram", discord.ButtonStyle.danger))
        self.add_item(PointButton("Watch Video (punishment)", "video", discord.ButtonStyle.danger))
        self.add_item(PointButton("Watch Reel (punishment)", "reel", discord.ButtonStyle.danger))
        self.add_item(PointButton("Open Game (punishment)", "open_game", discord.ButtonStyle.danger))
        self.add_item(PointButton("DARE (big)", "dare", discord.ButtonStyle.secondary))
        self.add_item(PointButton("DOUBLE DARE (huge)", "double_dare", discord.ButtonStyle.secondary))
        # Nourishment (positive)
        self.add_item(PointButton("Timetable chunk (nourish)", "timetable_chunk", discord.ButtonStyle.success))
        self.add_item(PointButton("Make grad video (nourish)", "make_grad_video", discord.ButtonStyle.success))
        self.add_item(PointButton("Reconnect with friends (nourish)", "reconnect_friends", discord.ButtonStyle.success))

# --- Bot commands ---
@bot.event
async def on_ready():
    init_db()
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    print("------")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID)) if GUILD_ID else await bot.tree.sync()
        print(f"Slash commands synced ({len(synced)}).")
    except Exception as e:
        print("Could not sync commands:", e)

# Send a persistent interactive scoreboard message (admin-only)
@bot.command(name="post_buttons")
@commands.has_permissions(administrator=True)
async def post_buttons(ctx: commands.Context):
    """Post the interactive points panel (admins only)."""
    view = PointsView(timeout=None)
    embed = discord.Embed(
        title="Focus Points Panel",
        description="Click the buttons below to self-report actions. Punishments deduct points; nourishment grants points.\n"
                    "Use `/mypoints` to check your balance. Admins can use `!setpoints @user number`.",
        color=discord.Color.blurple()
    )
    await ctx.send(embed=embed, view=view)

@bot.command(name="force_add")
@commands.has_permissions(administrator=True)
async def force_add(ctx: commands.Context, member: discord.Member, delta: int):
    """Admin command: add (or subtract) points from a user."""
    new = add_points(member.id, delta)
    await ctx.send(f"Updated {member.mention} by {delta:+d}. New total: {new} points.")

@bot.command(name="setpoints")
@commands.has_permissions(administrator=True)
async def setpoints(ctx: commands.Context, member: discord.Member, points: int):
    set_points(member.id, points)
    await ctx.send(f"Set {member.mention}'s points to {points}.")

@bot.command(name="mypoints")
async def mypoints(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    pts = get_points(member.id)
    await ctx.send(f"{member.mention} has **{pts}** points.")

@bot.command(name="leaderboard")
async def leaderboard(ctx: commands.Context):
    rows = top_leaderboard(10)
    if not rows:
        await ctx.send("Leaderboard is empty.")
        return
    desc = []
    for idx, (user_id, pts) in enumerate(rows, start=1):
        user = bot.get_user(user_id)
        name = user.name if user else f"User ID {user_id}"
        desc.append(f"**{idx}.** {name} — {pts} pts")
    embed = discord.Embed(title="Points Leaderboard", description="\n".join(desc), color=discord.Color.gold())
    await ctx.send(embed=embed)

@bot.command(name="reset_points")
@commands.has_permissions(administrator=True)
async def reset_points(ctx: commands.Context, member: discord.Member = None):
    if member:
        set_points(member.id, 0)
        await ctx.send(f"Reset {member.mention}'s points to 0.")
    else:
        # reset ALL (dangerous)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET points = 0, last_updated = ?", (datetime.utcnow().isoformat(),))
        conn.commit()
        conn.close()
        await ctx.send("Reset all users' points to 0.")

# Slash command to open panel (alternative to post_buttons)
@bot.tree.command(name="panel", description="Post the interactive points panel")
async def panel(interaction: discord.Interaction):
    # permission check: only allow in guilds
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    member = interaction.user
    # allow only admins to post
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only server admins may create the panel.", ephemeral=True)
        return
    view = PointsView(timeout=None)
    embed = discord.Embed(
        title="Focus Points Panel",
        description="Click the buttons below to self-report actions. Punishments deduct points; nourishment grants points.\n"
                    "Use `/mypoints` to check your balance.",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=view)

# Optional: button to display user's recent history (could be expanded)
@bot.command(name="history")
async def history(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    pts = get_points(member.id)
    await ctx.send(f"{member.mention} current points: {pts}. (Detailed event history not implemented.)")

# Run bot
if __name__ == "__main__":
    init_db()
    bot.run(TOKEN)
