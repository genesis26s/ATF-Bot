"""
OTF-Bot — A full-featured Discord bot
Features:
  • Moderation        (13 commands)
  • Welcome / Goodbye (7  commands)
  • Logging           (7  commands)
  • Ticket system      (9  commands, with a full admin dashboard UI)
  • Help               (1  command)

Two config sources:
  .env         — secrets only (BOT_TOKEN). See .env.example.
  config.json  — everything else about the bot itself: its name, embed
                 color, status/presence, and profile (avatar/banner).
                 Auto-created with defaults on first run if missing —
                 just edit it and restart the bot to apply changes.

Note: a bot's "About Me" bio text can only be set in the Discord
Developer Portal (https://discord.com/developers/applications) — the
API does not expose it for bots to edit themselves, so it's not part
of config.json. Username, avatar, and banner CAN be set from here,
but Discord rate-limits how often those change (roughly a couple of
times per hour), so the update_*_on_startup flags default to false —
turn one on, restart once to apply it, then turn it back off.

Requires Python 3.9+ and discord.py 2.3+  (pip install -U discord.py python-dotenv)
"""

# ── .env.example ───────────────────────────────
# BOT_TOKEN=your_token_here
# ───────────────────────────────────────────────

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import os
import datetime
import re
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
#  SECRETS  (from .env)
# ──────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in your .env file!")
# ──────────────────────────────────────────────

# ══════════════════════════════════════════════
#  BOT CONFIG  (config.json — name, status, embed color, profile)
# ══════════════════════════════════════════════
BOT_CONFIG_FILE = "config.json"

DEFAULT_BOT_CONFIG = {
    "bot_name": "OTF-Bot",
    "embed_color": "2F3136",
    "presence": {
        "status": "online",              # online | idle | dnd | invisible
        "activity_type": "playing",      # playing | watching | listening | competing | streaming
        "activity_text": "/help"
    },
    "profile": {
        "avatar_path": "",
        "banner_path": "",
        "update_username_on_startup": False,
        "update_avatar_on_startup": False,
        "update_banner_on_startup": False
    }
}

def load_bot_config() -> dict:
    """Loads config.json, creating it with defaults on first run.
    Missing keys are backfilled from the defaults so a partially-edited
    file never crashes the bot."""
    if not os.path.exists(BOT_CONFIG_FILE):
        with open(BOT_CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_BOT_CONFIG, f, indent=2)
        print(f"[OTF-Bot] Created default {BOT_CONFIG_FILE} — edit it to customize the bot, then restart.")
        return json.loads(json.dumps(DEFAULT_BOT_CONFIG))

    with open(BOT_CONFIG_FILE, "r") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError:
            print(f"[OTF-Bot] {BOT_CONFIG_FILE} contains invalid JSON — using defaults instead.")
            cfg = {}

    merged = {**DEFAULT_BOT_CONFIG, **cfg}
    merged["presence"] = {**DEFAULT_BOT_CONFIG["presence"], **cfg.get("presence", {})}
    merged["profile"] = {**DEFAULT_BOT_CONFIG["profile"], **cfg.get("profile", {})}
    return merged

BOT_CONFIG = load_bot_config()

_color_raw = str(BOT_CONFIG.get("embed_color", "2F3136")).lstrip("#")
try:
    DEFAULT_COLOR = int(_color_raw, 16)
except ValueError:
    DEFAULT_COLOR = 0x2F3136
    print(f"[OTF-Bot] Invalid embed_color in {BOT_CONFIG_FILE} — falling back to #2F3136.")

STATUS_TEXT = BOT_CONFIG.get("presence", {}).get("activity_text", "/help")

ACTIVITY_TYPE_MAP = {
    "playing": discord.ActivityType.playing,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}
PRESENCE_STATUS_MAP = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}

# ── intents ────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.moderation = True

# ── bot ────────────────────────────────────────
class OTFBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await self.tree.sync()

    async def _apply_presence(self):
        presence = BOT_CONFIG.get("presence", {})
        status = PRESENCE_STATUS_MAP.get(str(presence.get("status", "online")).lower(), discord.Status.online)
        activity_type_str = str(presence.get("activity_type", "playing")).lower()
        text = presence.get("activity_text", "/help")
        if activity_type_str == "streaming":
            activity = discord.Streaming(name=text, url="https://www.twitch.tv/discord")
        else:
            activity = discord.Activity(type=ACTIVITY_TYPE_MAP.get(activity_type_str, discord.ActivityType.playing), name=text)
        await self.change_presence(status=status, activity=activity)

    async def _apply_image(self, path: str, kind: str):
        if not path or not os.path.exists(path):
            print(f"[OTF-Bot] {kind} update skipped — file not found: {path!r}")
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
            if kind == "avatar":
                await self.user.edit(avatar=data)
            else:
                await self.user.edit(banner=data)
            print(f"[OTF-Bot] {kind} updated from {path}")
        except discord.HTTPException as ex:
            print(f"[OTF-Bot] Could not update {kind} (likely rate-limited — try again later): {ex}")

    async def _apply_profile_settings(self):
        profile = BOT_CONFIG.get("profile", {})
        desired_name = BOT_CONFIG.get("bot_name")
        if profile.get("update_username_on_startup") and desired_name and self.user.name != desired_name:
            try:
                await self.user.edit(username=desired_name)
                print(f"[OTF-Bot] Username updated to {desired_name}")
            except discord.HTTPException as ex:
                print(f"[OTF-Bot] Could not update username (likely rate-limited — try again later): {ex}")
        if profile.get("update_avatar_on_startup"):
            await self._apply_image(profile.get("avatar_path", ""), "avatar")
        if profile.get("update_banner_on_startup"):
            await self._apply_image(profile.get("banner_path", ""), "banner")

    async def on_ready(self):
        await self._apply_presence()
        await self._apply_profile_settings()
        print(f"[OTF-Bot] Logged in as {self.user} ({self.user.id})")

bot = OTFBot()

# ══════════════════════════════════════════════
#  PERSISTENCE  — simple JSON-backed store (per-server settings, separate from config.json)
# ══════════════════════════════════════════════
DATA_FILE = "otfbot_data.json"
_LEGACY_DATA_FILES = ["ctabot_data.json", "atfbot_data.json", "eflbot_data.json"]  # auto-migrated from older installs

if not os.path.exists(DATA_FILE):
    for _legacy_path in _LEGACY_DATA_FILES:
        if os.path.exists(_legacy_path):
            try:
                with open(_legacy_path, "r") as _f:
                    _legacy_contents = _f.read()
                with open(DATA_FILE, "w") as _f:
                    _f.write(_legacy_contents)
                print(f"[OTF-Bot] Migrated data from {_legacy_path} -> {DATA_FILE}")
            except Exception as _ex:
                print(f"[OTF-Bot] Could not migrate legacy data file {_legacy_path}: {_ex}")
            break

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def guild_cfg(guild_id: int) -> dict:
    data = load_data()
    key = str(guild_id)
    if key not in data:
        data[key] = {}
        save_data(data)
    return data[key]

def set_guild_cfg(guild_id: int, cfg: dict):
    data = load_data()
    data[str(guild_id)] = cfg
    save_data(data)

# ══════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════
def parse_duration(text: str) -> Optional[int]:
    """Convert strings like '10m', '2h', '1d' -> seconds."""
    match = re.fullmatch(r"(\d+)([smhd])", text.strip().lower())
    if not match:
        return None
    n, unit = int(match.group(1)), match.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]

def validate_hex(hex_str: str) -> Optional[int]:
    """Strictly validate a 6-digit hex color. Returns None if invalid."""
    if not hex_str:
        return None
    cleaned = hex_str.strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", cleaned):
        return int(cleaned, 16)
    return None

def safe_hex_to_color(hex_str: Optional[str], fallback: int = DEFAULT_COLOR) -> int:
    """Never raises — falls back to a safe default for corrupted/legacy stored values."""
    result = validate_hex(hex_str) if hex_str else None
    return result if result is not None else fallback

def slugify_key(text: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return key[:20] or "type"

def make_embed(title: str, description: str, color: int = DEFAULT_COLOR,
               footer: Optional[str] = None, thumbnail: Optional[str] = None,
               image: Optional[str] = None, author_name: Optional[str] = None,
               author_icon: Optional[str] = None, timestamp: bool = False) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color)
    if footer:
        e.set_footer(text=footer)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    if image:
        e.set_image(url=image)
    if author_name:
        e.set_author(name=author_name, icon_url=author_icon)
    if timestamp:
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return e

def _check_hierarchy(interaction: discord.Interaction, target: discord.Member) -> Optional[str]:
    """Pre-flight hierarchy / self-protection checks for punitive mod actions.
    Returns a user-facing error string if the action should be blocked, else None."""
    guild = interaction.guild
    if target.id == interaction.user.id:
        return "❌ You can't use this on yourself."
    if target.id == bot.user.id:
        return "❌ I can't use this on myself."
    if target.id == guild.owner_id:
        return "❌ You can't use this on the server owner."
    if isinstance(interaction.user, discord.Member) and interaction.user.id != guild.owner_id:
        if target.top_role >= interaction.user.top_role:
            return "❌ You can't act on someone with an equal or higher role than you."
    if target.top_role >= guild.me.top_role:
        return "❌ I can't act on that member — their highest role is equal to or above mine."
    return None

# ── safe UI base classes ───────────────────────
# Any error raised inside a button/select/modal callback is caught here
# instead of leaving the user with a silently-hanging interaction.
class SafeView(discord.ui.View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print(f"[OTF-Bot] View error on {item}: {error!r}")
        msg = "❌ Something went wrong. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

class SafeModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"[OTF-Bot] Modal error: {error!r}")
        msg = "❌ Something went wrong. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

# ══════════════════════════════════════════════
#  UNIFIED LOGGING  (used by both moderation actions and auto-logged events)
# ══════════════════════════════════════════════
LOG_EVENT_KEYS = [
    "message_delete", "message_edit", "voice_join", "voice_leave",
    "ban", "unban", "kick", "mute", "unmute", "warn", "purge", "lock", "unlock", "role",
]

async def _log(guild: discord.Guild, event: str, text: str, color: int = DEFAULT_COLOR):
    cfg = guild_cfg(guild.id)
    if not cfg.get("log_channel"):
        return
    if not cfg.get(f"log_{event}", True):
        return
    ch = guild.get_channel(int(cfg["log_channel"]))
    if not ch:
        return
    mode = cfg.get("log_mode", "embed")
    try:
        if mode == "text":
            await ch.send(f"[{event.upper()}] {text}")
        else:
            color_to_use = safe_hex_to_color(cfg.get("log_embed_color"), color)
            e = make_embed(f"📋 {event.replace('_', ' ').title()}", text, color_to_use, timestamp=True)
            await ch.send(embed=e)
    except (discord.Forbidden, discord.HTTPException) as ex:
        print(f"[OTF-Bot] Failed to send log for '{event}' in guild {guild.id}: {ex}")

# ══════════════════════════════════════════════
#  GLOBAL ERROR HANDLER
#  (fixes silent "This interaction failed" errors across every command)
# ══════════════════════════════════════════════
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ You don't have permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        missing = ", ".join(error.missing_permissions)
        msg = f"❌ I'm missing permissions to do that: **{missing}**."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ This command is on cooldown. Try again in {error.retry_after:.1f}s."
    else:
        original = getattr(error, "original", error)
        if isinstance(original, discord.Forbidden):
            msg = "❌ I don't have permission to do that. Check my role position and channel permissions."
        elif isinstance(original, discord.NotFound):
            msg = "❌ That user, role, or channel couldn't be found — it may have been deleted."
        elif isinstance(original, discord.HTTPException):
            msg = "❌ Discord rejected that request. Please check your input and try again."
        else:
            msg = "❌ Something went wrong running that command."
        cmd_name = interaction.command.name if interaction.command else "unknown"
        print(f"[OTF-Bot] Unhandled error in /{cmd_name}: {error!r}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

# ══════════════════════════════════════════════
#  SECTION 1 — MODERATION  (13 commands)
# ══════════════════════════════════════════════

@bot.tree.command(name="ban", description="Ban a member from the server.")
@app_commands.describe(member="The member to ban", reason="Reason for the ban", delete_days="Days of messages to delete (0-7)")
@app_commands.default_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member,
              reason: str = "No reason provided", delete_days: int = 0):
    err = _check_hierarchy(interaction, member)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    delete_days = max(0, min(delete_days, 7))
    await member.ban(reason=f"{interaction.user}: {reason}", delete_message_seconds=delete_days * 86400)
    e = make_embed("🔨 Member Banned", f"{member.mention} was banned.\n**Reason:** {reason}", 0xE74C3C, timestamp=True)
    await interaction.response.send_message(embed=e)
    await _log(interaction.guild, "ban", f"**User:** {member} ({member.id})\n**Mod:** {interaction.user}\n**Reason:** {reason}", 0xE74C3C)

@bot.tree.command(name="unban", description="Unban a user by their ID.")
@app_commands.describe(user_id="The user ID to unban", reason="Reason for unban")
@app_commands.default_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    if not user_id.isdigit():
        await interaction.response.send_message("❌ That doesn't look like a valid user ID.", ephemeral=True)
        return
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
    except discord.NotFound:
        await interaction.response.send_message("❌ That user isn't banned or doesn't exist.", ephemeral=True)
        return
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unban members.", ephemeral=True)
        return

    e = make_embed("✅ User Unbanned", f"{user} (`{user_id}`) has been unbanned.", 0x2ECC71, timestamp=True)
    await interaction.response.send_message(embed=e)
    await _log(interaction.guild, "unban", f"**User:** {user} ({user_id})\n**Mod:** {interaction.user}\n**Reason:** {reason}", 0x2ECC71)

@bot.tree.command(name="kick", description="Kick a member from the server.")
@app_commands.describe(member="The member to kick", reason="Reason for the kick")
@app_commands.default_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    err = _check_hierarchy(interaction, member)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    await member.kick(reason=f"{interaction.user}: {reason}")
    e = make_embed("👢 Member Kicked", f"{member.mention} was kicked.\n**Reason:** {reason}", 0xE67E22, timestamp=True)
    await interaction.response.send_message(embed=e)
    await _log(interaction.guild, "kick", f"**User:** {member} ({member.id})\n**Mod:** {interaction.user}\n**Reason:** {reason}", 0xE67E22)

MAX_TIMEOUT_SECONDS = 28 * 86400  # Discord's hard cap on timeouts

@bot.tree.command(name="mute", description="Timeout a member for a duration.")
@app_commands.describe(member="The member to mute", duration="Duration e.g. 10m, 2h, 1d (max 28d)", reason="Reason")
@app_commands.default_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member,
               duration: str = "10m", reason: str = "No reason provided"):
    secs = parse_duration(duration)
    if not secs:
        await interaction.response.send_message("❌ Invalid duration. Use e.g. `10m`, `2h`, `1d`.", ephemeral=True)
        return
    if secs > MAX_TIMEOUT_SECONDS:
        await interaction.response.send_message("❌ Timeouts can't exceed **28 days** (Discord's limit).", ephemeral=True)
        return
    err = _check_hierarchy(interaction, member)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    until = discord.utils.utcnow() + datetime.timedelta(seconds=secs)
    await member.timeout(until, reason=reason)
    e = make_embed("🔇 Member Muted", f"{member.mention} has been timed out for **{duration}**.\n**Reason:** {reason}", 0xF39C12, timestamp=True)
    await interaction.response.send_message(embed=e)
    await _log(interaction.guild, "mute", f"**User:** {member}\n**Duration:** {duration}\n**Mod:** {interaction.user}\n**Reason:** {reason}", 0xF39C12)

@bot.tree.command(name="unmute", description="Remove timeout from a member.")
@app_commands.describe(member="The member to unmute")
@app_commands.default_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    e = make_embed("🔊 Member Unmuted", f"{member.mention}'s timeout has been removed.", 0x2ECC71, timestamp=True)
    await interaction.response.send_message(embed=e)
    await _log(interaction.guild, "unmute", f"**User:** {member}\n**Mod:** {interaction.user}", 0x2ECC71)

@bot.tree.command(name="warn", description="Warn a member.")
@app_commands.describe(member="The member to warn", reason="Reason for the warning")
@app_commands.default_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    if member.id == bot.user.id:
        await interaction.response.send_message("❌ I can't warn myself.", ephemeral=True)
        return
    data = load_data()
    key = str(interaction.guild.id)
    if key not in data:
        data[key] = {}
    warns = data[key].setdefault("warnings", {}).setdefault(str(member.id), [])
    warns.append({
        "reason": reason,
        "mod": str(interaction.user),
        "time": str(datetime.datetime.now(datetime.timezone.utc)),
    })
    save_data(data)
    count = len(warns)
    e = make_embed("⚠️ Member Warned", f"{member.mention} has been warned.\n**Reason:** {reason}\n**Total warnings:** {count}", 0xF1C40F, timestamp=True)
    await interaction.response.send_message(embed=e)
    try:
        await member.send(embed=make_embed("⚠️ You received a warning", f"**Server:** {interaction.guild.name}\n**Reason:** {reason}", 0xF1C40F))
    except discord.Forbidden:
        pass
    await _log(interaction.guild, "warn", f"**User:** {member}\n**Mod:** {interaction.user}\n**Reason:** {reason}\n**Total:** {count}", 0xF1C40F)

@bot.tree.command(name="warnings", description="View warnings for a member.")
@app_commands.describe(member="The member to check")
@app_commands.default_permissions(manage_messages=True)
async def warnings(interaction: discord.Interaction, member: discord.Member):
    data = load_data()
    warns = data.get(str(interaction.guild.id), {}).get("warnings", {}).get(str(member.id), [])
    if not warns:
        await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)
        return
    desc = "\n".join(f"**{i+1}.** {w['reason']} — *{w['mod']}* at {w['time'][:19]}" for i, w in enumerate(warns))
    e = make_embed(f"⚠️ Warnings — {member}", desc[:4000], 0xF1C40F)
    await interaction.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member.")
@app_commands.describe(member="The member to clear warnings for")
@app_commands.default_permissions(manage_guild=True)
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    data = load_data()
    key = str(interaction.guild.id)
    if key in data and "warnings" in data[key] and str(member.id) in data[key]["warnings"]:
        data[key]["warnings"][str(member.id)] = []
        save_data(data)
    await interaction.response.send_message(f"✅ Cleared all warnings for {member.mention}.", ephemeral=True)

@bot.tree.command(name="purge", description="Bulk-delete messages in a channel.")
@app_commands.describe(amount="Number of messages to delete (1-100)", member="Only delete from this member (optional)")
@app_commands.default_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int, member: Optional[discord.Member] = None):
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("❌ This command can only be used in a text channel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    amount = max(1, min(amount, 100))
    def check(m):
        return (member is None) or (m.author == member)
    deleted = await interaction.channel.purge(limit=amount, check=check)
    await interaction.followup.send(f"🗑️ Deleted **{len(deleted)}** messages.", ephemeral=True)
    await _log(interaction.guild, "purge", f"**Channel:** {interaction.channel.mention}\n**Amount:** {len(deleted)}\n**Mod:** {interaction.user}", 0x95A5A6)

@bot.tree.command(name="slowmode", description="Set slowmode in the current channel.")
@app_commands.describe(seconds="Slowmode delay in seconds (0 to disable, max 21600)")
@app_commands.default_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int):
    seconds = max(0, min(seconds, 21600))
    await interaction.channel.edit(slowmode_delay=seconds)
    msg = f"⏱️ Slowmode set to **{seconds}s** in {interaction.channel.mention}." if seconds > 0 else f"⏱️ Slowmode disabled in {interaction.channel.mention}."
    await interaction.response.send_message(msg)

@bot.tree.command(name="lock", description="Lock a channel so members cannot send messages.")
@app_commands.describe(channel="Channel to lock (defaults to current)")
@app_commands.default_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    ch = channel or interaction.channel
    overwrite = ch.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(f"🔒 {ch.mention} has been locked.")
    await _log(interaction.guild, "lock", f"**Channel:** {ch.mention}\n**Mod:** {interaction.user}", 0xE74C3C)

@bot.tree.command(name="unlock", description="Unlock a channel.")
@app_commands.describe(channel="Channel to unlock (defaults to current)")
@app_commands.default_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    ch = channel or interaction.channel
    overwrite = ch.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(f"🔓 {ch.mention} has been unlocked.")
    await _log(interaction.guild, "unlock", f"**Channel:** {ch.mention}\n**Mod:** {interaction.user}", 0x2ECC71)

@bot.tree.command(name="role", description="Add or remove a role from a member.")
@app_commands.describe(action="add or remove", member="Target member", role="The role")
@app_commands.choices(action=[app_commands.Choice(name="add", value="add"), app_commands.Choice(name="remove", value="remove")])
@app_commands.default_permissions(manage_roles=True)
async def role(interaction: discord.Interaction, action: app_commands.Choice[str],
               member: discord.Member, role: discord.Role):
    if role.position >= interaction.guild.me.top_role.position:
        await interaction.response.send_message("❌ I can't manage that role — it's equal to or higher than my top role.", ephemeral=True)
        return
    if isinstance(interaction.user, discord.Member) and interaction.user.id != interaction.guild.owner_id:
        if role.position >= interaction.user.top_role.position:
            await interaction.response.send_message("❌ You can't manage a role equal to or higher than your own top role.", ephemeral=True)
            return

    if action.value == "add":
        if role in member.roles:
            await interaction.response.send_message(f"❌ {member.mention} already has {role.mention}.", ephemeral=True)
            return
        await member.add_roles(role)
        msg = f"✅ Added {role.mention} to {member.mention}."
    else:
        if role not in member.roles:
            await interaction.response.send_message(f"❌ {member.mention} doesn't have {role.mention}.", ephemeral=True)
            return
        await member.remove_roles(role)
        msg = f"✅ Removed {role.mention} from {member.mention}."
    await interaction.response.send_message(msg)
    await _log(interaction.guild, "role",
               f"**Action:** {'Added' if action.value == 'add' else 'Removed'}\n**User:** {member}\n**Role:** {role.name}\n**Mod:** {interaction.user}",
               0x9B59B6)

# ══════════════════════════════════════════════
#  SECTION 2 — WELCOME / GOODBYE  (7 commands)
# ══════════════════════════════════════════════
#
#  Config keys under guild config:
#    welcome_channel, welcome_mode (embed|text), welcome_message,
#    welcome_embed_*  (title, color, footer, thumbnail, image)
#    goodbye_channel, goodbye_mode, goodbye_message, goodbye_embed_*
# ──────────────────────────────────────────────

async def _send_welcome_goodbye(guild: discord.Guild, member: discord.Member, kind: str):
    cfg = guild_cfg(guild.id)
    ch_id = cfg.get(f"{kind}_channel")
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if not ch:
        return

    default_msg = (
        f"Welcome to **{guild.name}**, {member.mention}! 🎉"
        if kind == "welcome"
        else f"Goodbye, **{member.name}**. We'll miss you! 👋"
    )
    raw_msg = cfg.get(f"{kind}_message", default_msg)
    raw_msg = (raw_msg.replace("{user}", member.mention)
                       .replace("{username}", member.name)
                       .replace("{server}", guild.name)
                       .replace("{count}", str(guild.member_count)))

    mode = cfg.get(f"{kind}_mode", "embed")
    try:
        if mode == "text":
            await ch.send(raw_msg)
        else:
            color = safe_hex_to_color(cfg.get(f"{kind}_embed_color"), DEFAULT_COLOR)
            title = cfg.get(f"{kind}_embed_title", "Welcome!" if kind == "welcome" else "Goodbye!")
            footer = cfg.get(f"{kind}_embed_footer", f"{guild.name}")
            thumbnail = cfg.get(f"{kind}_embed_thumbnail") or str(member.display_avatar.url)
            image = cfg.get(f"{kind}_embed_image", "")
            e = make_embed(title, raw_msg, color, footer=footer,
                           thumbnail=thumbnail if thumbnail else None,
                           image=image if image else None, timestamp=True)
            await ch.send(embed=e)
    except (discord.Forbidden, discord.HTTPException) as ex:
        print(f"[OTF-Bot] Failed to send {kind} message in guild {guild.id}: {ex}")

@bot.event
async def on_member_join(member: discord.Member):
    await _send_welcome_goodbye(member.guild, member, "welcome")

@bot.event
async def on_member_remove(member: discord.Member):
    await _send_welcome_goodbye(member.guild, member, "goodbye")

# /setwelcome — set welcome channel
@bot.tree.command(name="setwelcome", description="Set the welcome channel.")
@app_commands.describe(channel="Channel to send welcome messages in")
@app_commands.default_permissions(manage_guild=True)
async def setwelcome(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = guild_cfg(interaction.guild.id)
    cfg["welcome_channel"] = str(channel.id)
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Welcome channel set to {channel.mention}.")

# /setgoodbye — set goodbye channel
@bot.tree.command(name="setgoodbye", description="Set the goodbye channel.")
@app_commands.describe(channel="Channel to send goodbye messages in")
@app_commands.default_permissions(manage_guild=True)
async def setgoodbye(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = guild_cfg(interaction.guild.id)
    cfg["goodbye_channel"] = str(channel.id)
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Goodbye channel set to {channel.mention}.")

# /welcomemode — embed or text
@bot.tree.command(name="welcomemode", description="Set welcome message mode: embed or text.")
@app_commands.describe(mode="embed or text")
@app_commands.choices(mode=[app_commands.Choice(name="embed", value="embed"), app_commands.Choice(name="text", value="text")])
@app_commands.default_permissions(manage_guild=True)
async def welcomemode(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    cfg = guild_cfg(interaction.guild.id)
    cfg["welcome_mode"] = mode.value
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Welcome mode set to **{mode.value}**.")

# /goodbyemode — embed or text
@bot.tree.command(name="goodbyemode", description="Set goodbye message mode: embed or text.")
@app_commands.describe(mode="embed or text")
@app_commands.choices(mode=[app_commands.Choice(name="embed", value="embed"), app_commands.Choice(name="text", value="text")])
@app_commands.default_permissions(manage_guild=True)
async def goodbyemode(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    cfg = guild_cfg(interaction.guild.id)
    cfg["goodbye_mode"] = mode.value
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Goodbye mode set to **{mode.value}**.")

# /welcomemessage — set message text (supports {user}, {username}, {server}, {count})
@bot.tree.command(name="welcomemessage", description="Set the welcome message text.")
@app_commands.describe(message="Message text. Use {user} {username} {server} {count} as placeholders.")
@app_commands.default_permissions(manage_guild=True)
async def welcomemessage(interaction: discord.Interaction, message: str):
    cfg = guild_cfg(interaction.guild.id)
    cfg["welcome_message"] = message
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message("✅ Welcome message set.")

# /goodbyemessage
@bot.tree.command(name="goodbyemessage", description="Set the goodbye message text.")
@app_commands.describe(message="Message text. Use {user} {username} {server} {count} as placeholders.")
@app_commands.default_permissions(manage_guild=True)
async def goodbyemessage(interaction: discord.Interaction, message: str):
    cfg = guild_cfg(interaction.guild.id)
    cfg["goodbye_message"] = message
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message("✅ Goodbye message set.")

# /customizeembed — customize welcome or goodbye embed
@bot.tree.command(name="customizeembed", description="Customize the welcome or goodbye embed.")
@app_commands.describe(
    kind="welcome or goodbye",
    title="Embed title",
    color="Hex color e.g. 2ECC71",
    footer="Footer text",
    thumbnail="Thumbnail image URL (leave blank to use member avatar)",
    image="Large image URL (optional)"
)
@app_commands.choices(kind=[app_commands.Choice(name="welcome", value="welcome"), app_commands.Choice(name="goodbye", value="goodbye")])
@app_commands.default_permissions(manage_guild=True)
async def customizeembed(interaction: discord.Interaction,
                         kind: app_commands.Choice[str],
                         title: Optional[str] = None,
                         color: Optional[str] = None,
                         footer: Optional[str] = None,
                         thumbnail: Optional[str] = None,
                         image: Optional[str] = None):
    cfg = guild_cfg(interaction.guild.id)
    k = kind.value

    if color:
        color_int = validate_hex(color)
        if color_int is None:
            await interaction.response.send_message("❌ Invalid hex color. Use a 6-digit hex code like `2ECC71`.", ephemeral=True)
            return
        cfg[f"{k}_embed_color"] = color.strip().lstrip("#")

    if title:
        cfg[f"{k}_embed_title"] = title
    if footer:
        cfg[f"{k}_embed_footer"] = footer
    if thumbnail:
        cfg[f"{k}_embed_thumbnail"] = thumbnail
    if image:
        cfg[f"{k}_embed_image"] = image
    set_guild_cfg(interaction.guild.id, cfg)

    preview_color = safe_hex_to_color(cfg.get(f"{k}_embed_color"), DEFAULT_COLOR)
    preview = make_embed(
        cfg.get(f"{k}_embed_title", "Preview"),
        f"This is a preview of your **{k}** embed.",
        preview_color,
        footer=cfg.get(f"{k}_embed_footer"),
        thumbnail=cfg.get(f"{k}_embed_thumbnail"),
        image=cfg.get(f"{k}_embed_image") or None,
        timestamp=True
    )
    await interaction.response.send_message("✅ Embed updated! Here's a preview:", embed=preview)

# ══════════════════════════════════════════════
#  SECTION 3 — LOGGING  (7 commands)
# ══════════════════════════════════════════════
#
#  Config keys: log_channel, log_mode (embed|text), log_embed_color,
#               log_*  booleans for each event type (see LOG_EVENT_KEYS)
# ──────────────────────────────────────────────

# Auto-log events
@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    await _log(message.guild, "message_delete",
               f"**Author:** {message.author}\n**Channel:** {message.channel.mention}\n**Content:** {message.content[:900] or '(empty)'}",
               0xE74C3C)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    await _log(before.guild, "message_edit",
               f"**Author:** {before.author}\n**Channel:** {before.channel.mention}\n**Before:** {before.content[:400]}\n**After:** {after.content[:400]}",
               0x3498DB)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if before.channel == after.channel:
        return
    if after.channel:
        await _log(member.guild, "voice_join", f"**{member}** joined **{after.channel.name}**", 0x2ECC71)
    elif before.channel:
        await _log(member.guild, "voice_leave", f"**{member}** left **{before.channel.name}**", 0xE74C3C)

# /setlogchannel
@bot.tree.command(name="setlogchannel", description="Set the logging channel.")
@app_commands.describe(channel="Channel to send logs to")
@app_commands.default_permissions(manage_guild=True)
async def setlogchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = guild_cfg(interaction.guild.id)
    cfg["log_channel"] = str(channel.id)
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.")

# /logmode
@bot.tree.command(name="logmode", description="Set log output mode: embed or text.")
@app_commands.describe(mode="embed or text")
@app_commands.choices(mode=[app_commands.Choice(name="embed", value="embed"), app_commands.Choice(name="text", value="text")])
@app_commands.default_permissions(manage_guild=True)
async def logmode(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    cfg = guild_cfg(interaction.guild.id)
    cfg["log_mode"] = mode.value
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Log mode set to **{mode.value}**.")

# /logtoggle — enable/disable individual log event types
@bot.tree.command(name="logtoggle", description="Enable or disable a specific log event type.")
@app_commands.describe(event="Event name", enabled="Enable or disable")
@app_commands.choices(
    event=[app_commands.Choice(name=k, value=k) for k in LOG_EVENT_KEYS],
    enabled=[app_commands.Choice(name="enable", value="1"), app_commands.Choice(name="disable", value="0")]
)
@app_commands.default_permissions(manage_guild=True)
async def logtoggle(interaction: discord.Interaction,
                    event: app_commands.Choice[str],
                    enabled: app_commands.Choice[str]):
    cfg = guild_cfg(interaction.guild.id)
    cfg[f"log_{event.value}"] = bool(int(enabled.value))
    set_guild_cfg(interaction.guild.id, cfg)
    state = "enabled" if int(enabled.value) else "disabled"
    await interaction.response.send_message(f"✅ Logging for **{event.value}** is now **{state}**.")

# /logstatus — show current logging configuration
@bot.tree.command(name="logstatus", description="Show current logging configuration.")
@app_commands.default_permissions(manage_guild=True)
async def logstatus(interaction: discord.Interaction):
    cfg = guild_cfg(interaction.guild.id)
    ch_id = cfg.get("log_channel")
    ch = interaction.guild.get_channel(int(ch_id)) if ch_id else None
    mode = cfg.get("log_mode", "embed")
    lines = [f"**Channel:** {ch.mention if ch else 'Not set'}", f"**Mode:** {mode}", ""]
    for ev in LOG_EVENT_KEYS:
        tick = "✅" if cfg.get(f"log_{ev}", True) else "❌"
        lines.append(f"{tick} {ev}")
    e = make_embed("📋 Logging Status", "\n".join(lines), DEFAULT_COLOR)
    await interaction.response.send_message(embed=e, ephemeral=True)

# /logtest — post a test log entry
@bot.tree.command(name="logtest", description="Send a test entry to the log channel.")
@app_commands.default_permissions(manage_guild=True)
async def logtest(interaction: discord.Interaction):
    cfg = guild_cfg(interaction.guild.id)
    if not cfg.get("log_channel"):
        await interaction.response.send_message("❌ No log channel is set. Use `/setlogchannel` first.", ephemeral=True)
        return
    await _log(interaction.guild, "message_delete", f"✅ Log test triggered by {interaction.user}", 0x9B59B6)
    await interaction.response.send_message("✅ Test log sent.", ephemeral=True)

# /logclear — unset log channel (disable logging)
@bot.tree.command(name="logclear", description="Disable logging by clearing the log channel.")
@app_commands.default_permissions(manage_guild=True)
async def logclear(interaction: discord.Interaction):
    cfg = guild_cfg(interaction.guild.id)
    cfg.pop("log_channel", None)
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message("✅ Logging disabled.")

# /logembedcolor — customize log embed color (respected by _log)
@bot.tree.command(name="logembedcolor", description="Set the default color for log embeds.")
@app_commands.describe(color="Hex color code e.g. 2F3136")
@app_commands.default_permissions(manage_guild=True)
async def logembedcolor(interaction: discord.Interaction, color: str):
    color_int = validate_hex(color)
    if color_int is None:
        await interaction.response.send_message("❌ Invalid hex color. Use a 6-digit hex code like `2F3136`.", ephemeral=True)
        return
    cfg = guild_cfg(interaction.guild.id)
    cfg["log_embed_color"] = color.strip().lstrip("#")
    set_guild_cfg(interaction.guild.id, cfg)
    e = discord.Embed(title="🎨 Log embed color updated", description="All future log embeds will use this color.", color=color_int)
    await interaction.response.send_message(embed=e)

# ══════════════════════════════════════════════
#  SECTION 4 — TICKET SYSTEM  (9 commands + full admin dashboard UI)
# ══════════════════════════════════════════════
#
#  Config keys: ticket_category, ticket_support_role, ticket_log_channel,
#               ticket_count, open_tickets { user_id: channel_id },
#               ticket_types { type_key: {label, description, emoji, category, support_role} },
#               ticket_panel_title, ticket_panel_description, ticket_panel_color
#
#  The public ticket panel (button/dropdown + close button) is routed through
#  the raw on_interaction dispatcher below rather than persistent Views, so it
#  keeps working correctly even after the bot restarts. The admin dashboard's
#  buttons/selects/modals use normal short-lived discord.py Views since they
#  only need to survive a single configuration session.
# ──────────────────────────────────────────────

DEFAULT_PANEL_COLOR = "2B2D31"

def _build_ticket_panel(guild: discord.Guild):
    """Returns (embed, view) for the public-facing ticket panel."""
    cfg = guild_cfg(guild.id)
    types = cfg.get("ticket_types", {})
    title = cfg.get("ticket_panel_title") or "🎫 Support Tickets"
    color_int = safe_hex_to_color(cfg.get("ticket_panel_color"), int(DEFAULT_PANEL_COLOR, 16))
    description = cfg.get("ticket_panel_description") or (
        "Select a ticket category below to get started." if types else "Click the button below to open a support ticket."
    )
    e = make_embed(title, description, color_int, footer=guild.name,
                   thumbnail=str(guild.icon.url) if guild.icon else None)
    view = discord.ui.View(timeout=None)
    if types:
        options = []
        for key, t in list(types.items())[:25]:
            options.append(discord.SelectOption(
                label=t["label"][:100], value=key,
                description=(t.get("description") or None),
                emoji=t.get("emoji") or None
            ))
        select = discord.ui.Select(placeholder="Select a type of ticket", custom_id="ticket_type_select",
                                    options=options, min_values=1, max_values=1)
        view.add_item(select)
    else:
        view.add_item(discord.ui.Button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="open_ticket"))
    return e, view

async def _create_ticket_channel(interaction: discord.Interaction, type_key: Optional[str] = None):
    cfg = guild_cfg(interaction.guild.id)
    open_tickets = cfg.get("open_tickets", {})
    uid = str(interaction.user.id)

    if uid in open_tickets:
        existing_ch = interaction.guild.get_channel(int(open_tickets[uid]))
        if existing_ch:
            await interaction.response.send_message(f"❌ You already have an open ticket: {existing_ch.mention}", ephemeral=True)
            return
        open_tickets.pop(uid, None)  # stale entry — channel was deleted outside the bot

    type_info = None
    name_prefix = "ticket"
    if type_key:
        type_info = cfg.get("ticket_types", {}).get(type_key)
        if not type_info:
            await interaction.response.send_message("❌ That ticket category no longer exists. Please contact staff.", ephemeral=True)
            return
        name_prefix = re.sub(r"[^a-z0-9-]", "", type_info["label"].lower().replace(" ", "-"))[:20] or "ticket"

    cat_id = (type_info or {}).get("category") or cfg.get("ticket_category")
    category = interaction.guild.get_channel(int(cat_id)) if cat_id else None
    if category and not isinstance(category, discord.CategoryChannel):
        category = None

    count = cfg.get("ticket_count", 0) + 1

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    support_role_id = (type_info or {}).get("support_role") or cfg.get("ticket_support_role")
    if support_role_id:
        support_role = interaction.guild.get_role(int(support_role_id))
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    try:
        ch = await interaction.guild.create_text_channel(
            f"{name_prefix}-{count:04d}",
            category=category,
            overwrites=overwrites,
            topic=f"Ticket by {interaction.user} ({interaction.user.id})"
        )
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to create ticket channels here.", ephemeral=True)
        return

    cfg["ticket_count"] = count
    open_tickets[uid] = str(ch.id)
    cfg["open_tickets"] = open_tickets
    set_guild_cfg(interaction.guild.id, cfg)

    label = type_info["label"] if type_info else "Support"
    e = make_embed(
        "🎫 Ticket Opened",
        f"Hello {interaction.user.mention}! **{label}** — support will be with you shortly.\n\nDescribe your issue below and press **Close Ticket** when done.",
        0x5865F2, footer=f"Ticket #{count:04d}", timestamp=True
    )
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Close Ticket", style=discord.ButtonStyle.red, emoji="🔒", custom_id="close_ticket"))
    await ch.send(content=f"{interaction.user.mention}", embed=e, view=view)
    await interaction.response.send_message(f"✅ Your ticket has been created: {ch.mention}", ephemeral=True)

    log_ch_id = cfg.get("ticket_log_channel")
    if log_ch_id:
        log_ch = interaction.guild.get_channel(int(log_ch_id))
        if log_ch:
            le = make_embed("🎫 Ticket Opened", f"**User:** {interaction.user}\n**Category:** {label}\n**Channel:** {ch.mention}\n**Ticket #:** {count}", 0x2ECC71, timestamp=True)
            try:
                await log_ch.send(embed=le)
            except (discord.Forbidden, discord.HTTPException):
                pass

async def _close_ticket_button(interaction: discord.Interaction):
    cfg = guild_cfg(interaction.guild.id)
    open_tickets = cfg.get("open_tickets", {})
    owner_id = next((uid for uid, cid in open_tickets.items() if cid == str(interaction.channel.id)), None)

    is_support = interaction.user.guild_permissions.manage_channels
    if not is_support:
        role_ids = set()
        if cfg.get("ticket_support_role"):
            role_ids.add(cfg["ticket_support_role"])
        for t in cfg.get("ticket_types", {}).values():
            if t.get("support_role"):
                role_ids.add(t["support_role"])
        user_role_ids = {str(r.id) for r in interaction.user.roles}
        is_support = bool(role_ids & user_role_ids)

    if not is_support:
        await interaction.response.send_message("❌ You don't have permission to close this ticket.", ephemeral=True)
        return

    await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")

    if owner_id:
        open_tickets.pop(owner_id, None)
        cfg["open_tickets"] = open_tickets
        set_guild_cfg(interaction.guild.id, cfg)

    log_ch_id = cfg.get("ticket_log_channel")
    if log_ch_id:
        log_ch = interaction.guild.get_channel(int(log_ch_id))
        if log_ch:
            e = make_embed("🎫 Ticket Closed", f"**Channel:** {interaction.channel.name}\n**Closed by:** {interaction.user}", 0xE74C3C, timestamp=True)
            try:
                await log_ch.send(embed=e)
            except (discord.Forbidden, discord.HTTPException):
                pass

    await asyncio.sleep(5)
    try:
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
    except discord.Forbidden:
        pass

# Raw component dispatcher — always fires regardless of bot restarts,
# so the PUBLIC ticket buttons/selects never silently break like persistent Views can.
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    cid = interaction.data.get("custom_id", "")
    try:
        if cid == "open_ticket":
            await _create_ticket_channel(interaction)
        elif cid == "ticket_type_select":
            values = interaction.data.get("values", [])
            if values:
                await _create_ticket_channel(interaction, type_key=values[0])
        elif cid == "close_ticket":
            await _close_ticket_button(interaction)
    except Exception as ex:
        print(f"[OTF-Bot] Error handling component '{cid}': {ex!r}")
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("❌ Something went wrong processing that action.", ephemeral=True)
            except Exception:
                pass

# ── Admin dashboard UI ──────────────────────────

class CategoryRoleStepView(SafeView):
    """Step 3 of the add/edit wizard — optionally attach a support role."""
    def __init__(self, key: str, label: str):
        super().__init__(timeout=180)
        self.key = key
        self.label = label

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="🛡️ Optional: pick a support role...", min_values=0, max_values=1)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role_id = select.values[0].id if select.values else None
        cfg = guild_cfg(interaction.guild.id)
        types = cfg.get("ticket_types", {})
        if self.key in types:
            types[self.key]["support_role"] = str(role_id) if role_id else None
            cfg["ticket_types"] = types
            set_guild_cfg(interaction.guild.id, cfg)
        msg = f"✅ **{self.label}** is fully configured" + (f" with support role <@&{role_id}>." if role_id else ", with no dedicated support role.")
        await interaction.response.edit_message(content=msg, view=None)

    @discord.ui.button(label="Keep As-Is / Skip", style=discord.ButtonStyle.secondary)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"✅ **{self.label}** saved.", view=None)


class CategoryChannelSelectView(SafeView):
    """Step 2 of the add/edit wizard — pick the Discord category channel."""
    def __init__(self, name: str, description: str, emoji: str, editing_key: str):
        super().__init__(timeout=180)
        self.name = name
        self.description = description
        self.emoji = emoji
        self.editing_key = editing_key

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.category],
                       placeholder="📁 Select the ticket category channel...")
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        category_id = select.values[0].id
        cfg = guild_cfg(interaction.guild.id)
        types = cfg.get("ticket_types", {})
        existing_role = types.get(self.editing_key, {}).get("support_role")
        types[self.editing_key] = {
            "label": self.name[:100],
            "description": (self.description[:100] if self.description else None),
            "emoji": self.emoji or None,
            "category": str(category_id),
            "support_role": existing_role,
        }
        cfg["ticket_types"] = types
        set_guild_cfg(interaction.guild.id, cfg)
        await interaction.response.edit_message(
            content=f"✅ Category channel set for **{self.name}**. Optionally choose a support role below:",
            view=CategoryRoleStepView(key=self.editing_key, label=self.name)
        )


class AddCategoryModal(SafeModal, title="Add Ticket Category"):
    name = discord.ui.TextInput(label="Category Name", placeholder="e.g. League Support", max_length=100)
    description = discord.ui.TextInput(label="Description (optional)", placeholder="Shown under the name in the dropdown", max_length=100, required=False)
    emoji = discord.ui.TextInput(label="Emoji (optional)", placeholder="e.g. ❗", max_length=10, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = guild_cfg(interaction.guild.id)
        types = cfg.get("ticket_types", {})
        key = slugify_key(self.name.value)
        if key not in types and len(types) >= 24:
            await interaction.response.send_message("❌ Maximum of 24 ticket categories reached (Discord dropdown limit).", ephemeral=True)
            return
        view = CategoryChannelSelectView(name=self.name.value, description=self.description.value, emoji=self.emoji.value, editing_key=key)
        await interaction.response.send_message(f"Now choose the category channel for **{self.name.value}**:", view=view, ephemeral=True)


class EditCategoryModal(SafeModal, title="Edit Ticket Category"):
    def __init__(self, key: str, existing: dict):
        super().__init__()
        self.key = key
        self.name = discord.ui.TextInput(label="Category Name", default=existing.get("label", ""), max_length=100)
        self.description = discord.ui.TextInput(label="Description (optional)", default=existing.get("description") or "", max_length=100, required=False)
        self.emoji = discord.ui.TextInput(label="Emoji (optional)", default=existing.get("emoji") or "", max_length=10, required=False)
        self.add_item(self.name)
        self.add_item(self.description)
        self.add_item(self.emoji)

    async def on_submit(self, interaction: discord.Interaction):
        view = CategoryChannelSelectView(name=self.name.value, description=self.description.value, emoji=self.emoji.value, editing_key=self.key)
        await interaction.response.send_message(f"Now choose the category channel for **{self.name.value}** (or re-pick the same one):", view=view, ephemeral=True)


class SelectExistingTypeView(SafeView):
    """Used by both 'Edit Category' and 'Delete Category' buttons."""
    def __init__(self, guild_id: int, action: str):
        super().__init__(timeout=120)
        self.action = action
        cfg = guild_cfg(guild_id)
        types = cfg.get("ticket_types", {})
        options = [
            discord.SelectOption(label=t["label"][:100], value=k, emoji=t.get("emoji") or None,
                                 description=(t.get("description") or None))
            for k, t in list(types.items())[:25]
        ]
        select = discord.ui.Select(placeholder=f"Choose a category to {action}...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        key = interaction.data["values"][0]
        cfg = guild_cfg(interaction.guild.id)
        types = cfg.get("ticket_types", {})
        t = types.get(key)
        if not t:
            await interaction.response.send_message("❌ That category no longer exists.", ephemeral=True)
            return
        if self.action == "edit":
            await interaction.response.send_modal(EditCategoryModal(key=key, existing=t))
        else:
            types.pop(key, None)
            cfg["ticket_types"] = types
            set_guild_cfg(interaction.guild.id, cfg)
            await interaction.response.edit_message(content=f"🗑️ Deleted ticket category **{t['label']}**.", view=None)


class PanelEmbedModal(SafeModal, title="Edit Ticket Panel Embed"):
    def __init__(self, existing_title: str, existing_desc: str, existing_color: str):
        super().__init__()
        self.title_input = discord.ui.TextInput(label="Panel Title", default=existing_title, max_length=100)
        self.desc_input = discord.ui.TextInput(label="Panel Description", style=discord.TextStyle.paragraph,
                                                default=existing_desc or "", required=False, max_length=300)
        self.color_input = discord.ui.TextInput(label="Theme Color (hex)", default=existing_color, max_length=7)
        self.add_item(self.title_input)
        self.add_item(self.desc_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        color_int = validate_hex(self.color_input.value)
        if color_int is None:
            await interaction.response.send_message("❌ Invalid hex color — use a 6-digit code like `2B2D31`.", ephemeral=True)
            return
        cfg = guild_cfg(interaction.guild.id)
        cfg["ticket_panel_title"] = self.title_input.value
        cfg["ticket_panel_description"] = self.desc_input.value or None
        cfg["ticket_panel_color"] = self.color_input.value.strip().lstrip("#")
        set_guild_cfg(interaction.guild.id, cfg)
        await interaction.response.send_message("✅ Panel embed updated. Use **Post Ticket Panel** to publish it.", ephemeral=True)


class PostPanelChannelSelectView(SafeView):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select a channel...")
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        channel = interaction.guild.get_channel(select.values[0].id)
        if not channel:
            await interaction.response.edit_message(content="❌ Couldn't find that channel.", view=None)
            return
        e, view = _build_ticket_panel(interaction.guild)
        try:
            await channel.send(embed=e, view=view)
        except discord.Forbidden:
            await interaction.response.edit_message(content=f"❌ I don't have permission to send messages in {channel.mention}.", view=None)
            return
        await interaction.response.edit_message(content=f"✅ Ticket panel posted in {channel.mention}.", view=None)


def _build_dashboard_embed(guild: discord.Guild) -> discord.Embed:
    cfg = guild_cfg(guild.id)
    types = cfg.get("ticket_types", {})
    color_hex = cfg.get("ticket_panel_color", DEFAULT_PANEL_COLOR)
    e = discord.Embed(
        title="🎫 OTF Ticket System Dashboard",
        description=(
            "Welcome to the **Ticket Admin Control Centre**!\n"
            "Use the interactive buttons below to fully customize your support system, "
            "add, edit, or remove ticket categories, or post the public panel."
        ),
        color=safe_hex_to_color(color_hex, int(DEFAULT_PANEL_COLOR, 16))
    )
    e.add_field(name="Active Categories", value=f"`{len(types)}` configured", inline=True)
    e.add_field(name="Panel Theme Color", value=f"`#{color_hex.upper()}`", inline=True)
    e.set_footer(text="OTF Bot • Support System Control")
    return e


class TicketDashboardView(SafeView):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Add Category", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddCategoryModal())

    @discord.ui.button(label="Edit Category", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not guild_cfg(interaction.guild.id).get("ticket_types"):
            await interaction.response.send_message("❌ No ticket categories exist yet. Use **Add Category** first.", ephemeral=True)
            return
        view = SelectExistingTypeView(interaction.guild.id, action="edit")
        await interaction.response.send_message("Choose a category to edit:", view=view, ephemeral=True)

    @discord.ui.button(label="Delete Category", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def delete_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not guild_cfg(interaction.guild.id).get("ticket_types"):
            await interaction.response.send_message("❌ No ticket categories exist yet.", ephemeral=True)
            return
        view = SelectExistingTypeView(interaction.guild.id, action="delete")
        await interaction.response.send_message("Choose a category to delete:", view=view, ephemeral=True)

    @discord.ui.button(label="Edit Panel Embed", emoji="🎨", style=discord.ButtonStyle.secondary, row=1)
    async def edit_panel_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = guild_cfg(interaction.guild.id)
        modal = PanelEmbedModal(
            existing_title=cfg.get("ticket_panel_title", "🎫 Support Tickets"),
            existing_desc=cfg.get("ticket_panel_description", "") or "",
            existing_color=cfg.get("ticket_panel_color", DEFAULT_PANEL_COLOR),
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="View Categories", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def view_categories(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = guild_cfg(interaction.guild.id)
        types = cfg.get("ticket_types", {})
        if not types:
            await interaction.response.send_message("No ticket categories configured yet.", ephemeral=True)
            return
        lines = []
        for t in types.values():
            cat = interaction.guild.get_channel(int(t["category"])) if t.get("category") else None
            role = interaction.guild.get_role(int(t["support_role"])) if t.get("support_role") else None
            line = f"{t.get('emoji') or '🎫'} **{t['label']}**"
            if t.get("description"):
                line += f"\n> {t['description']}"
            line += f"\n→ {cat.name if cat else 'Unknown category'}" + (f" · {role.mention}" if role else "")
            lines.append(line)
        e = make_embed("🎫 Ticket Categories", "\n\n".join(lines), safe_hex_to_color(cfg.get("ticket_panel_color"), DEFAULT_COLOR))
        await interaction.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Post Ticket Panel", emoji="🚀", style=discord.ButtonStyle.success, row=1)
    async def post_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PostPanelChannelSelectView()
        await interaction.response.send_message("Choose a channel to post the ticket panel in:", view=view, ephemeral=True)


# /ticketdashboard — the full admin control centre (matches the reference UI)
@bot.tree.command(name="ticketdashboard", description="Open the ticket system admin dashboard.")
@app_commands.default_permissions(manage_guild=True)
async def ticketdashboard(interaction: discord.Interaction):
    e = _build_dashboard_embed(interaction.guild)
    await interaction.response.send_message(embed=e, view=TicketDashboardView(), ephemeral=True)

# /ticketsetup — quick-post using the currently saved panel config
@bot.tree.command(name="ticketsetup", description="Post the ticket panel in a channel.")
@app_commands.describe(channel="Channel to post the panel in")
@app_commands.default_permissions(manage_guild=True)
async def ticketsetup(interaction: discord.Interaction, channel: discord.TextChannel):
    e, view = _build_ticket_panel(interaction.guild)
    try:
        await channel.send(embed=e, view=view)
    except discord.Forbidden:
        await interaction.response.send_message(f"❌ I don't have permission to send messages in {channel.mention}.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Ticket panel sent to {channel.mention}.", ephemeral=True)

# /ticketcategory — default/fallback category (used only when no category types are configured)
@bot.tree.command(name="ticketcategory", description="Set the default category used when no specific ticket category applies.")
@app_commands.describe(category="The category")
@app_commands.default_permissions(manage_guild=True)
async def ticketcategory(interaction: discord.Interaction, category: discord.CategoryChannel):
    cfg = guild_cfg(interaction.guild.id)
    cfg["ticket_category"] = str(category.id)
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Default ticket category set to **{category.name}**.")

# /ticketsupportrole — default/fallback support role
@bot.tree.command(name="ticketsupportrole", description="Set the default support role that can see all tickets.")
@app_commands.describe(role="The support role")
@app_commands.default_permissions(manage_guild=True)
async def ticketsupportrole(interaction: discord.Interaction, role: discord.Role):
    cfg = guild_cfg(interaction.guild.id)
    cfg["ticket_support_role"] = str(role.id)
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Default support role set to {role.mention}.")

# /ticketlogchannel
@bot.tree.command(name="ticketlogchannel", description="Set the channel where ticket logs are sent.")
@app_commands.describe(channel="Log channel")
@app_commands.default_permissions(manage_guild=True)
async def ticketlogchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = guild_cfg(interaction.guild.id)
    cfg["ticket_log_channel"] = str(channel.id)
    set_guild_cfg(interaction.guild.id, cfg)
    await interaction.response.send_message(f"✅ Ticket log channel set to {channel.mention}.")

# /adduser — add a user to the current ticket
@bot.tree.command(name="adduser", description="Add a user to the current ticket.")
@app_commands.describe(member="User to add")
@app_commands.default_permissions(manage_channels=True)
async def adduser(interaction: discord.Interaction, member: discord.Member):
    await interaction.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
    await interaction.response.send_message(f"✅ {member.mention} has been added to the ticket.")

# /removeuser — remove a user from the current ticket
@bot.tree.command(name="removeuser", description="Remove a user from the current ticket.")
@app_commands.describe(member="User to remove")
@app_commands.default_permissions(manage_channels=True)
async def removeuser(interaction: discord.Interaction, member: discord.Member):
    await interaction.channel.set_permissions(member, overwrite=None)
    await interaction.response.send_message(f"✅ {member.mention} has been removed from the ticket.")

# /renameticket — rename the ticket channel
@bot.tree.command(name="renameticket", description="Rename the current ticket channel.")
@app_commands.describe(name="New channel name")
@app_commands.default_permissions(manage_channels=True)
async def renameticket(interaction: discord.Interaction, name: str):
    await interaction.channel.edit(name=name)
    await interaction.response.send_message(f"✅ Ticket renamed to **{name}**.")

# /closeticket — close via command
@bot.tree.command(name="closeticket", description="Close the current ticket channel.")
@app_commands.default_permissions(manage_channels=True)
async def closeticket(interaction: discord.Interaction):
    cfg = guild_cfg(interaction.guild.id)
    open_tickets = cfg.get("open_tickets", {})
    owner_id = next((uid for uid, cid in open_tickets.items() if cid == str(interaction.channel.id)), None)

    await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")

    if owner_id:
        open_tickets.pop(owner_id, None)
        cfg["open_tickets"] = open_tickets
        set_guild_cfg(interaction.guild.id, cfg)

    log_ch_id = cfg.get("ticket_log_channel")
    if log_ch_id:
        log_ch = interaction.guild.get_channel(int(log_ch_id))
        if log_ch:
            e = make_embed("🎫 Ticket Closed", f"**Channel:** {interaction.channel.name}\n**Closed by:** {interaction.user}", 0xE74C3C, timestamp=True)
            try:
                await log_ch.send(embed=e)
            except (discord.Forbidden, discord.HTTPException):
                pass

    await asyncio.sleep(5)
    try:
        await interaction.channel.delete(reason="Ticket closed by command")
    except discord.Forbidden:
        pass

# ══════════════════════════════════════════════
#  HELP COMMAND
# ══════════════════════════════════════════════

HELP_SECTIONS = {
    "🛡️ Moderation": [
        ("/ban",           "Ban a member from the server"),
        ("/unban",         "Unban a user by their ID"),
        ("/kick",          "Kick a member from the server"),
        ("/mute",          "Timeout a member (e.g. 10m, 2h, 1d)"),
        ("/unmute",        "Remove a timeout from a member"),
        ("/warn",          "Issue a warning to a member"),
        ("/warnings",      "View all warnings for a member"),
        ("/clearwarnings", "Clear all warnings for a member"),
        ("/purge",         "Bulk-delete messages in a channel"),
        ("/slowmode",      "Set slowmode delay in a channel"),
        ("/lock",          "Lock a channel — members can't send"),
        ("/unlock",        "Unlock a channel"),
        ("/role",          "Add or remove a role from a member"),
    ],
    "👋 Welcome / Goodbye": [
        ("/setwelcome",     "Set the welcome channel"),
        ("/setgoodbye",     "Set the goodbye channel"),
        ("/welcomemode",    "Switch welcome between embed / text"),
        ("/goodbyemode",    "Switch goodbye between embed / text"),
        ("/welcomemessage", "Set welcome message text (supports placeholders)"),
        ("/goodbyemessage", "Set goodbye message text (supports placeholders)"),
        ("/customizeembed", "Customize welcome or goodbye embed (color, title…)"),
    ],
    "📋 Logging": [
        ("/setlogchannel",  "Set the log channel"),
        ("/logmode",        "Switch logs between embed / text"),
        ("/logtoggle",      "Enable or disable a specific log event"),
        ("/logstatus",      "Show current logging configuration"),
        ("/logtest",        "Send a test entry to the log channel"),
        ("/logclear",       "Disable logging by clearing the log channel"),
        ("/logembedcolor",  "Set the default color for log embeds"),
    ],
    "🎫 Tickets": [
        ("/ticketdashboard",   "Open the full admin dashboard (add/edit/delete categories, post panel)"),
        ("/ticketsetup",       "Quick-post the ticket panel to a channel"),
        ("/ticketcategory",    "Set the default fallback category"),
        ("/ticketsupportrole", "Set the default support role"),
        ("/ticketlogchannel",  "Set where ticket logs are sent"),
        ("/adduser",           "Add a user to the current ticket"),
        ("/removeuser",        "Remove a user from the current ticket"),
        ("/renameticket",      "Rename the current ticket channel"),
        ("/closeticket",       "Close the current ticket channel"),
    ],
}

SECTION_KEYS = list(HELP_SECTIONS.keys())

class HelpView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.current = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current == len(SECTION_KEYS) - 1
        self.page_btn.label = f"{self.current + 1} / {len(SECTION_KEYS)}"

    def build_embed(self) -> discord.Embed:
        section = SECTION_KEYS[self.current]
        commands_list = HELP_SECTIONS[section]
        desc = "\n".join(f"`{cmd}` — {desc}" for cmd, desc in commands_list)
        e = discord.Embed(title=f"{section}", description=desc, color=DEFAULT_COLOR)
        e.set_footer(text=f"OTF-Bot • Use /help to navigate • {len(commands_list)} commands in this section")
        return e

    async def _update(self, interaction: discord.Interaction):
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This menu isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1
        await self._update(interaction)

    @discord.ui.button(label="1 / 4", style=discord.ButtonStyle.primary, disabled=True)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # display only

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1
        await self._update(interaction)


@bot.tree.command(name="help", description="Browse all OTF-Bot commands.")
async def help_command(interaction: discord.Interaction):
    view = HelpView(author_id=interaction.user.id)
    await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

# ══════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════
bot.run(BOT_TOKEN)
