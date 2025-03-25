"""
This module contains the code for managing events within a Discord bot.

It allows users to create, join, leave, and mark events as completed.
The bot also sends reminders for upcoming events and updates event statuses (Upcoming, Ongoing, Completed).

Features:
- Event creation with role assignment
- Joining and leaving events with role management
- Sending reminders and event status updates
- Host transfer functionality
- RSVP caps and live editing of event details
"""

import sqlite3
from datetime import datetime, timedelta, timezone
import json
import pytz
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.errors import NotFound, Forbidden, HTTPException

# Load configuration from config.json
try:
    with open("config.json", "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    TOKEN = config["TOKEN"]
    GUILD_ID = config["GUILD_ID"]
except (FileNotFoundError, json.JSONDecodeError):
    print("❌ Error: `config.json` is missing or invalid. Ensure it exists and is formatted correctly.")
    exit(1)

# Bot setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Event command group and subcommands
event_group = app_commands.Group(
    name="event",
    description="Event management commands."
)
edit_group = app_commands.Group(
    name="edit",
    description="Edit an event's details."
)
event_group.add_command(edit_group)
tree.add_command(event_group)


def execute_query(query, params=()):
    """Executes a SQL query with proper connection handling."""
    with sqlite3.connect("events.db") as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.fetchall()


def setup_database():
    """Initializes the database table structure if it doesn't exist."""
    with sqlite3.connect("events.db") as connection:
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                title TEXT PRIMARY KEY,
                date TEXT,
                time TEXT,
                description TEXT,
                attendees TEXT,
                message_id TEXT,
                role_id INTEGER,
                channel_id INTEGER,
                host TEXT,
                status TEXT DEFAULT 'Upcoming',
                created_at TEXT,
                max_attendees INTEGER DEFAULT NULL
            )
        """)
        connection.commit()


setup_database()

async def autocomplete_event_titles(interaction: discord.Interaction, current: str):
    """Suggests up to 25 matching event titles based on user input."""
    results = execute_query("SELECT title FROM events")
    titles = [row[0] for row in results if row[0].lower().startswith(current.lower())]
    return [app_commands.Choice(name=title, value=title) for title in titles[:25]]

@tasks.loop(minutes=1)
async def check_event_reminders():
    """Checks if events are happening soon, updates statuses, and sends reminders."""
    current_time = datetime.now(timezone.utc)  # Current UTC time (timezone-aware)
    future_time = current_time + timedelta(minutes=30)  # Time 30 minutes from now
    future_time_str = future_time.strftime("%H:%M UTC")  # Format future time for comparison

    sent_reminders = set()  # Prevent duplicate reminders

    # Send 30-minute reminders
    events_near = execute_query("SELECT title FROM events WHERE time = ?", (future_time_str,))

    for (title,) in events_near:
        event_data = get_event_data(title)
        if not event_data:
            continue  # Skip if event not found

        if title in sent_reminders:
            continue  # Skip duplicate reminders for the same event

        # Send reminder message in the event channel
        channel = bot.get_channel(event_data["channel_id"])
        if channel:
            role = discord.utils.get(channel.guild.roles, id=event_data["role_id"])
            if role:
                await channel.send(f"⏳ <@&{role.id}>, your event **'{title}'** starts in **30 minutes!**")
                sent_reminders.add(title)  # Mark as sent

    # Find events transitioning to "Ongoing" based on event date and time
    events_to_update = execute_query("SELECT title, date, time FROM events WHERE status = 'Upcoming'")

    for title, event_date, event_time in events_to_update:
        event_data = get_event_data(title)
        if not event_data:
            continue

        # Combine date and time to create full event start datetime
        event_start_str = f"{event_date} {event_time}"
        try:
            event_start_time = datetime.strptime(event_start_str, "%d-%m-%Y %H:%M UTC").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        current_time_obj = datetime.now(timezone.utc)

        # Check if the event start time has passed
        if current_time_obj >= event_start_time:
            execute_query("UPDATE events SET status = 'Ongoing' WHERE title = ?", (title,))
            event_data["status"] = "Ongoing"

            channel = bot.get_channel(event_data["channel_id"])
            if channel:
                role = discord.utils.get(channel.guild.roles, id=event_data["role_id"])
                if role:
                    await channel.send(f"🚀 <@&{role.id}>, **'{title}'** has now **started!** 🎉")

            await display_event(channel, event_data)


def get_event_data(title):
    event = execute_query("""
        SELECT title, date, time, description, attendees, message_id,
               role_id, channel_id, host, status, created_at, max_attendees
        FROM events WHERE title = ?
    """, (title,))

    if not event:
        return None  # Return None if event doesn't exist

    event = event[0]  # Unpack tuple

    return {
        "title": event[0],
        "date": event[1],
        "time": event[2],
        "description": event[3],
        "attendees": event[4] if event[4] else "No participants yet",
        "message_id": event[5],
        "role_id": event[6],
        "channel_id": event[7],
        "host": event[8],
        "status": event[9],
        "created_at": event[10],
        "max_attendees": event[11] if len(event) > 11 else None

    }

async def display_event_embed_and_view(event_data):
    """
    Builds a polished embed and participation view for the given event.

    Args:
        event_data (dict): Dictionary containing all event details.

    Returns:
        tuple: discord.Embed, discord.ui.View
    """
    # Color based on event status
    status_colors = {
        "Upcoming": discord.Color.green(),
        "Ongoing": discord.Color.gold(),
        "Completed": discord.Color.red()
    }

    status_display = {
        "Upcoming": "🟢 Upcoming",
        "Ongoing": "🟡 Ongoing",
        "Completed": "🔴 Completed"
    }.get(event_data["status"], "❓ Unknown")

    embed = discord.Embed(
        title=f"📅 {event_data['title']}",
        description=f"📝 {event_data['description']}",
        color=status_colors.get(event_data["status"], discord.Color.greyple())
    )

    # Convert time and date
    event_time_utc = datetime.strptime(event_data['time'], "%H:%M UTC")
    event_date = datetime.strptime(event_data['date'], "%d-%m-%Y").replace(tzinfo=timezone.utc)

    # Combine into full datetime in UTC
    event_datetime = datetime.combine(event_date.date(), event_time_utc.time()).replace(tzinfo=timezone.utc)
    timestamp = int(event_datetime.timestamp())

    # Game Date and Time (UTC formatted as "Game Time")
    formatted_date = event_datetime.strftime("%m/%d/%Y")
    formatted_game_time = event_datetime.strftime("%H:%M")
    formatted_local_time = f"<t:{timestamp}:t>"  # No seconds

    # Countdown (live while upcoming, static if passed)
    current_time = datetime.now(timezone.utc)
    if event_datetime > current_time:
        countdown_text = f"<t:{timestamp}:R>"  # Discord auto-updating
    else:
        countdown_text = "Already started or in progress"

    # Add embed fields
    embed.add_field(name="📌 Status", value=f"**{status_display}**\n", inline=False)
    embed.add_field(name="📅 Date", value=f"**{formatted_date}**", inline=True)
    embed.add_field(name="🕒 Game Time", value=f"**{formatted_game_time}**", inline=True)
    embed.add_field(name="🕓 Local Time", value=f"{formatted_local_time}", inline=True)
    embed.add_field(name="⏳ Countdown", value=countdown_text, inline=False)

    # Participants
    attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []
    if event_data["host"] not in attendees_list:
        attendees_list.insert(0, event_data["host"])

    cap = event_data.get("max_attendees")
    participant_display = ""

    # Grouped user display (up to 4 per line)
    grouped_users = [
        " ".join(attendees_list[i:i+4])
        for i in range(0, len(attendees_list), 4)
    ]
    participant_display += "\n" + "\n".join(grouped_users)

    if cap is not None:
        open_slots = cap - len(attendees_list)
        if open_slots > 0:
            slot_text = "`Open Slot`"
            grouped_slots = [
                " ".join([slot_text] * min(4, open_slots - i))
                for i in range(0, open_slots, 4)
            ]
            participant_display += "\n" + "\n".join(grouped_slots)

        participant_display += f"\n\n**{len(attendees_list)}/{cap} slots filled**"
        if len(attendees_list) >= cap:
            participant_display += " 🔒 Full"

    embed.add_field(name="✅ Participants", value=participant_display or "No participants yet", inline=False)

    # Extra info
    created_at = datetime.strptime(event_data["created_at"], "%Y-%m-%d %H:%M:%S")
    formatted_creation_time = created_at.strftime("%b %d, %Y at %I:%M %p")
    info = (
        f"👤 **Host**: {event_data['host']}\n"
        f"🛠️ **Created**: {formatted_creation_time}\n"
        f"👥 **Team Size**: {len(attendees_list)}"
    )
    embed.add_field(name="ℹ️ Info", value="\n" + info, inline=False)

    embed.set_footer(text="\n\nClick a button below to join, leave, or complete the event!")

    view = ParticipationView(event_data["title"], event_data["host"])
    bot.add_view(view)
    return embed, view

async def display_event(ctx, event_data):
    """Displays or updates an event embed using event_data dictionary."""
    embed, view = await display_event_embed_and_view(event_data)

    if event_data["message_id"]:
        try:
            message = await ctx.fetch_message(int(event_data["message_id"]))
            await message.edit(embed=embed, view=view)
            return message
        except discord.NotFound:
            return await ctx.send(embed=embed, view=view)
    else:
        return await ctx.send(embed=embed, view=view)

class ParticipationView(discord.ui.View):
    """Interactive view with Join, Leave, and Complete buttons for event participation."""
    def __init__(self, event_title, event_host):
        super().__init__(timeout=None)
        self.event_title = event_title
        self.event_host = event_host  # Renamed to avoid shadowing 'host' in outer scope
        self.add_item(ParticipateButton(event_title))
        self.add_item(LeaveButton(event_title))
        self.add_item(CompleteEventButton(event_title, event_host))  # Updated to use 'event_host'

class CompleteEventButton(discord.ui.Button):
    """Button to allow the event host or an admin to mark an event as completed."""
    def __init__(self, event_title, event_host):
        super().__init__(label="Complete Event", style=discord.ButtonStyle.danger, custom_id=f"complete_{event_title}")
        self.event_title = event_title
        self.event_host = event_host  # Renamed from `host` to `event_host`

    async def callback(self, interaction: discord.Interaction):
        """Handles event completion when pressed by the host or an admin."""
        event_data = get_event_data(self.event_title)

        if not event_data:
            await interaction.response.send_message(f"❌ No event found with the title: `{self.event_title}`", ephemeral=True)
            return

        if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only the event host or an admin can complete this event.", ephemeral=True)
            return

        execute_query("UPDATE events SET status = 'Completed' WHERE title = ?", (self.event_title,))
        role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])
        if role:
            host_member = discord.utils.get(interaction.guild.members, mention=event_data["host"])
            if host_member:
                await host_member.remove_roles(role)

            attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []
            for participant in attendees_list:
                participant_member = discord.utils.get(interaction.guild.members, mention=participant)
                if participant_member:
                    await participant_member.remove_roles(role)

            if not role.members:
                await role.delete()
                execute_query("UPDATE events SET role_id = NULL WHERE title = ?", (self.event_title,))

        channel = bot.get_channel(event_data["channel_id"])
        if channel:
            role = discord.utils.get(channel.guild.roles, id=event_data["role_id"])
            if role:
                await channel.send(f"🎉 **Thank you for participating in '{self.event_title}'!** 🎉\n"
                                   f"<@&{role.id}>, this event has now concluded.")
            await display_completed_event(channel, event_data)

        execute_query("DELETE FROM events WHERE title = ?", (self.event_title,))
        await interaction.response.send_message(f"✅ Event **'{self.event_title}'** has been marked as **Completed**!", ephemeral=True)

async def display_completed_event(ctx, event_data):
    """
    Displays a polished final event embed after completion.

    Args:
        ctx: The context to send/edit the message in.
        event_data (dict): The event data dictionary.
    """
    embed = discord.Embed(
        title=f"📅 {event_data['title']}",
        description=f"📝 {event_data['description']}",
        color=discord.Color.red()
    )

    # Time and date formatting
    event_time_utc = datetime.strptime(event_data['time'], "%H:%M UTC")
    formatted_time = event_time_utc.strftime("%H:%M")
    event_date = datetime.strptime(event_data['date'], "%d-%m-%Y")
    formatted_date = event_date.strftime("%m/%d/%Y")

    embed.add_field(name="📌 Status", value="🔴 Completed", inline=False)
    embed.add_field(name="📅 Date", value=f"**{formatted_date}**", inline=True)
    embed.add_field(name="🕒 Time", value=f"**{formatted_time}** UTC", inline=True)

    # Participants
    attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []
    if event_data["host"] not in attendees_list:
        attendees_list.insert(0, event_data["host"])

    grouped_users = [
        " ".join(attendees_list[i:i+4])
        for i in range(0, len(attendees_list), 4)
    ]
    participants_text = "\n".join(grouped_users)

    embed.add_field(name="✅ Final Participants", value=participants_text or "No participants", inline=False)

    # Info section
    created_at = datetime.strptime(event_data["created_at"], "%Y-%m-%d %H:%M:%S")
    formatted_created = created_at.strftime("%b %d, %Y at %I:%M %p")
    info = (
        f"👤 **Host**: {event_data['host']}\n"
        f"🛠️ **Created**: {formatted_created}\n"
        f"👥 **Team Size**: {len(attendees_list)}"
    )
    embed.add_field(name="ℹ️ Info", value="\n" + info, inline=False)

    embed.set_footer(text="This event has now concluded. Thank you for participating!")

    # Edit or send new message
    if event_data["message_id"]:
        try:
            message = await ctx.fetch_message(int(event_data["message_id"]))
            await message.edit(embed=embed, view=None)
            return message
        except discord.NotFound:
            return await ctx.send(embed=embed)
    else:
        return await ctx.send(embed=embed)


class ParticipateButton(discord.ui.Button):
    """Button to allow users to join an event."""
    def __init__(self, event_title):
        super().__init__(label="Join Event", style=discord.ButtonStyle.success, custom_id=f"join_{event_title}")
        self.event_title = event_title

    async def callback(self, interaction: discord.Interaction):
        """Handles user participation in an event and recreates role if missing."""
        event_data = get_event_data(self.event_title)

        if not event_data:
            await interaction.response.send_message(f"❌ No event found with the title: `{self.event_title}`", ephemeral=True)
            return

        attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []
        max_cap = event_data.get("max_attendees")

        # Prevent duplicate join
        if interaction.user.mention in attendees_list:
            await interaction.response.send_message("❌ You are already participating!", ephemeral=True)
            return

        # Always include the host in the count (before checking cap)
        if event_data["host"] not in attendees_list:
            attendees_list.insert(0, event_data["host"])

        # Enforce max attendee cap
        if max_cap and len(attendees_list) >= max_cap:
            await interaction.response.send_message("❌ This event is full!", ephemeral=True)
            return

        attendees_list.append(interaction.user.mention)  # Add user to attendees
        formatted_attendees = ", ".join(attendees_list)

        execute_query("UPDATE events SET attendees = ? WHERE title = ?", (formatted_attendees, self.event_title))

        role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])

        # If role was deleted, recreate it and update DB
        if role is None:
            role_name = f"Event {self.event_title}"
            role = await interaction.guild.create_role(name=role_name)
            execute_query("UPDATE events SET role_id = ? WHERE title = ?", (role.id, self.event_title))
            print(f"♻️ Recreated missing role for event '{self.event_title}'")

        # Assign role if user doesn't already have it
        if role not in interaction.user.roles:
            await interaction.user.add_roles(role)
        event_data["attendees"] = formatted_attendees  # Update event data locally
        channel = bot.get_channel(event_data["channel_id"])
        if channel:
            await display_event(channel, event_data)

        await interaction.response.send_message(f"✅ {interaction.user.mention} has joined the event!", ephemeral=True)

class LeaveButton(discord.ui.Button):
    """Button to allow users to leave an event."""
    def __init__(self, event_title):
        super().__init__(label="Leave Event", style=discord.ButtonStyle.danger, custom_id=f"leave_{event_title}")
        self.event_title = event_title

    async def callback(self, interaction: discord.Interaction):
        """Handles user leaving an event and deletes empty roles."""
        event_data = get_event_data(self.event_title)

        if not event_data:
            await interaction.response.send_message(f"❌ No event found with the title: `{self.event_title}`", ephemeral=True)
            return

        attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []

        if interaction.user.mention == event_data["host"]:
            await interaction.response.send_message("❌ The host cannot leave the event.", ephemeral=True)
            return

        if interaction.user.mention in attendees_list:
            attendees_list.remove(interaction.user.mention)

            execute_query("UPDATE events SET attendees = ? WHERE title = ?", (", ".join(attendees_list), self.event_title))

            role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])
            if role:
                await interaction.user.remove_roles(role)

                # Re-check latest event data
                event_data = get_event_data(self.event_title)

                # Pull latest list of attendees
                remaining_attendees = event_data["attendees"].split(", ") if event_data["attendees"] else []

                # Check if current host is still an attendee
                host_still_attending = event_data["host"] in remaining_attendees

                # Only delete the role if no attendees and no host
                if not remaining_attendees and not host_still_attending:
                    await role.delete()
                    execute_query("UPDATE events SET role_id = NULL WHERE title = ?", (self.event_title,))
                    print(f"🗑 Deleted event role '{role.name}' because it had no remaining members.")
                else:
                    print(f"ℹ️ Role '{role.name}' not deleted — still in use.")


            event_data["attendees"] = ", ".join(attendees_list)

            channel = bot.get_channel(event_data["channel_id"])
            if channel:
                await display_event(channel, event_data)

            await interaction.response.send_message(f"❌ {interaction.user.mention} has left the event.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You are not in this event!", ephemeral=True)

# Slash Command: Create a New Event
@tree.command(name="host_event", description="Create a new event with title, date, time, and description.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    title="Title of the event",
    date="Date in DD-MM-YYYY format",
    time="Time in HH:MM (24h)",
    description="Details about the event",
    max_attendees="Max number of participants (optional)"
)
async def host_event(
    interaction: discord.Interaction,
    title: str,
    date: str,
    time: str,
    description: str,
    max_attendees: int = None
):
    """
    Slash command to create a new event.

    Args:
        interaction (discord.Interaction): The interaction from Discord.
        title (str): Event title.
        date (str): Date in DD-MM-YYYY format.
        time (str): Time in HH:MM (24h format).
        description (str): Description of the event.
        max_attendees (int, optional): Max number of participants.
    """
    await interaction.response.defer(thinking=True)

    # Check for duplicate event
    if get_event_data(title):
        await interaction.followup.send(f"❌ An event with the title '{title}' already exists.")
        return

    try:
        event_date = datetime.strptime(date, "%d-%m-%Y").strftime("%d-%m-%Y")
        utc_time = datetime.strptime(time, "%H:%M").replace(tzinfo=pytz.utc)
    except ValueError:
        await interaction.followup.send("❌ Invalid date or time format.")
        return

    # Create event role
    role = await interaction.guild.create_role(name=f"Event {title}")
    event_host = interaction.user.mention
    attendees = event_host

    if max_attendees is not None and max_attendees <= 0:
        max_attendees = None

    # Insert event into the database
    with sqlite3.connect("events.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events (
                title, date, time, description, attendees, message_id,
                role_id, channel_id, host, status, created_at, max_attendees
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title,
            event_date,
            utc_time.strftime("%H:%M UTC"),
            description,
            attendees,
            "",  # Message ID will be set after sending the embed
            role.id,
            interaction.channel_id,
            event_host,
            "Upcoming",
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            max_attendees
        ))
        conn.commit()

    # Assign role to the host
    await interaction.user.add_roles(role)

    # Build the embed and view, then send the initial response
    event_data = get_event_data(title)
    embed, view = await display_event_embed_and_view(event_data)
    await interaction.followup.send(embed=embed, view=view)

    # Update the message_id in the database
    message = await interaction.original_response()
    execute_query("UPDATE events SET message_id = ? WHERE title = ?", (str(message.id), title))

# Slash Command: Delete an Event
@tree.command(name="deleteevent", description="Delete a specific event and its associated data.")
@app_commands.describe(event_title="Title of the event to delete")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def deleteevent(interaction: discord.Interaction, event_title: str):
    """
    Slash command to delete a specific event, including its role, message, and database entry.

    Args:
        interaction (discord.Interaction): The interaction context.
        event_title (str): The title of the event to delete.
    """
    event_data = get_event_data(event_title)

    if not event_data:
        await interaction.response.send_message(
            f"❌ No event found with the title '{event_title}'.", ephemeral=True
        )
        return

    if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only the event host or an admin can delete this event.", ephemeral=True
        )
        return

    # Delete the associated role if it exists
    role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])
    if role:
        await role.delete()

    # Delete the associated message if it exists
    if event_data["message_id"]:
        channel = bot.get_channel(event_data["channel_id"])
        if channel:
            try:
                message = await channel.fetch_message(int(event_data["message_id"]))
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    # Remove the event from the database
    execute_query("DELETE FROM events WHERE title = ?", (event_title,))

    await interaction.response.send_message(f"🗑️ Event **'{event_title}'** has been deleted.")

@deleteevent.autocomplete("event_title")
async def deleteevent_autocomplete(interaction: discord.Interaction, current: str):
    """
    Provides autocomplete suggestions for the deleteevent command.
    """
    return await autocomplete_event_titles(interaction, current)

# Slash Command: Transfer Event Host
@tree.command(name="transferhost", description="Transfer event hosting to another participant.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    new_host="The user to transfer hosting to",
    event_title="Title of the event"
)
async def transferhost(
    interaction: discord.Interaction,
    new_host: discord.Member,
    event_title: str
):
    """
    Slash command to transfer event hosting to another participant.

    Args:
        interaction (discord.Interaction): The interaction from Discord.
        new_host (discord.Member): Member to transfer hosting to.
        event_title (str): Title of the event.
    """
    event_data = get_event_data(event_title)

    if not event_data:
        await interaction.response.send_message(
            f"❌ No event found with the title '{event_title}'.", ephemeral=True
        )
        return

    if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only the current host or an admin can transfer hosting.", ephemeral=True
        )
        return

    attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []
    if new_host.mention not in attendees_list:
        await interaction.response.send_message(
            f"❌ {new_host.mention} is not a participant in '{event_title}'.", ephemeral=True
        )
        return

    # Revoke role from old host
    old_host = discord.utils.get(interaction.guild.members, mention=event_data["host"])
    role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])
    if old_host and role:
        await old_host.remove_roles(role)

    # Grant role to new host if missing
    if role and role not in new_host.roles:
        await new_host.add_roles(role)

    # Update database and event info
    execute_query("UPDATE events SET host = ? WHERE title = ?", (new_host.mention, event_title))
    event_data["host"] = new_host.mention

    # Refresh embed
    channel = bot.get_channel(event_data["channel_id"])
    if channel:
        await display_event(channel, event_data)

    await interaction.response.send_message(
        f"✅ Host for '{event_title}' transferred to {new_host.mention}."
    )

@transferhost.autocomplete("event_title")
async def event_title_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    """
    Provides autocomplete suggestions for the transferhost command.
    """
    results = execute_query("SELECT title FROM events")
    titles = [row[0] for row in results if current.lower() in row[0].lower()]
    return [
        app_commands.Choice(name=title, value=title) for title in titles[:25]
    ]

# Slash Command: Delete All Events (Admin Only)
@tree.command(
    name="deleteallevents",
    description="Delete all events and their roles/messages (admin only)."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def deleteallevents(interaction: discord.Interaction):
    """
    Admin-only command to delete all events, their roles, and messages.
    """
    events = execute_query("SELECT title, role_id, message_id, channel_id FROM events")

    if not events:
        await interaction.response.send_message("✅ No events to delete.", ephemeral=True)
        return

    deleted_roles = []
    deleted_messages = 0

    for title, role_id, message_id, channel_id in events:
        # Delete associated role if it exists
        role = discord.utils.get(interaction.guild.roles, id=role_id)
        if role:
            await role.delete()
            deleted_roles.append(role.name)

        # Delete associated message if possible
        if message_id:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    message = await channel.fetch_message(int(message_id))
                    await message.delete()
                    deleted_messages += 1
                except (NotFound, Forbidden, HTTPException):
                    pass

        # Delete event from database
        execute_query("DELETE FROM events WHERE title = ?", (title,))

    # Summary message
    summary = (
        f"✅ Deleted all events.\n"
        f"🗑 Roles: {', '.join(deleted_roles) if deleted_roles else 'None'}\n"
        f"🧹 Messages: {deleted_messages}"
    )

    await interaction.response.send_message(summary, ephemeral=True)

# Slash Command: List All Commands
@tree.command(name="commands", description="List all available commands.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def list_commands(interaction: discord.Interaction):
    """
    Displays a list of available slash commands for users.

    Args:
        interaction (discord.Interaction): The interaction context.
    """
    commands_list = """
**Available Commands:**
- `/host_event` – Create a new event
- `/transferhost` – Transfer event host to another user
- `/deleteevent` – Delete a specific event
- `/deleteallevents` – Delete all events (admin only)
- `/edit time` – Edit the time of an event
- `/edit date` – Edit the date of an event
- `/edit description` – Edit the description of an event
- `/edit max` – Edit the maximum number of participants
- `/edit remove` – Remove a participant from an event
- `/commands` – Show this command list
    """
    await interaction.response.send_message(commands_list, ephemeral=True)

# Edit Commands for Event Management

@edit_group.command(name="time", description="Edit the time of an event.")
@app_commands.describe(event_title="Event to edit", time="New time (HH:MM)")
async def edit_time(interaction: discord.Interaction, event_title: str, time: str):
    """
    Edits the time of an existing event.
    """
    event_data = get_event_data(event_title)
    if not event_data:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only the host or an admin can edit this event.", ephemeral=True)
        return

    try:
        datetime.strptime(time, "%H:%M")
    except ValueError:
        await interaction.response.send_message("❌ Invalid time format. Use HH:MM (24h).", ephemeral=True)
        return

    execute_query("UPDATE events SET time = ? WHERE title = ?", (time + " UTC", event_title))
    channel = bot.get_channel(event_data["channel_id"])
    if channel:
        await display_event(channel, get_event_data(event_title))

    await interaction.response.send_message(f"✅ Updated time for '{event_title}'.", ephemeral=True)

@edit_group.command(name="date", description="Edit the date of an event.")
@app_commands.describe(event_title="Event to edit", date="New date (DD-MM-YYYY)")
async def edit_date(interaction: discord.Interaction, event_title: str, date: str):
    """
    Edits the date of an existing event.
    """
    event_data = get_event_data(event_title)
    if not event_data:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only the host or an admin can edit this event.", ephemeral=True)
        return

    try:
        datetime.strptime(date, "%d-%m-%Y")
    except ValueError:
        await interaction.response.send_message("❌ Invalid date format. Use DD-MM-YYYY.", ephemeral=True)
        return

    execute_query("UPDATE events SET date = ? WHERE title = ?", (date, event_title))
    channel = bot.get_channel(event_data["channel_id"])
    if channel:
        await display_event(channel, get_event_data(event_title))

    await interaction.response.send_message(f"✅ Updated date for '{event_title}'.", ephemeral=True)

@edit_group.command(name="description", description="Edit the event description.")
@app_commands.describe(event_title="Event to edit", description="New description")
async def edit_description(interaction: discord.Interaction, event_title: str, description: str):
    """
    Edits the description of an existing event.
    """
    event_data = get_event_data(event_title)
    if not event_data:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only the host or an admin can edit this event.", ephemeral=True)
        return

    if len(description) < 5:
        await interaction.response.send_message("❌ Description too short.", ephemeral=True)
        return

    execute_query("UPDATE events SET description = ? WHERE title = ?", (description, event_title))
    channel = bot.get_channel(event_data["channel_id"])
    if channel:
        await display_event(channel, get_event_data(event_title))

    await interaction.response.send_message(f"✅ Updated description for '{event_title}'.", ephemeral=True)

# Edit Command: Update Maximum Attendees
@edit_group.command(name="max", description="Edit the maximum number of participants.")
@app_commands.describe(
    event_title="The event you want to update",
    max_attendees="New max number of participants (0 for unlimited)"
)
async def edit_max(
    interaction: discord.Interaction,
    event_title: str,
    max_attendees: int
):
    """
    Updates the maximum number of attendees for a given event.

    Args:
        interaction (discord.Interaction): The interaction context.
        event_title (str): The title of the event.
        max_attendees (int): The new maximum number of participants.
    """
    event_data = get_event_data(event_title)

    if not event_data:
        await interaction.response.send_message(f"❌ Event '{event_title}' not found.", ephemeral=True)
        return

    if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only the host or an admin can update the cap.", ephemeral=True)
        return

    if max_attendees < 0:
        await interaction.response.send_message("❌ Max attendees cannot be negative.", ephemeral=True)
        return

    value = None if max_attendees == 0 else max_attendees

    execute_query("UPDATE events SET max_attendees = ? WHERE title = ?", (value, event_title))

    channel = bot.get_channel(event_data["channel_id"])
    if channel:
        await display_event(channel, get_event_data(event_title))

    msg = (
        f"✅ Max participants for **'{event_title}'** "
        f"updated to **{max_attendees if value else 'Unlimited'}**."
    )
    await interaction.response.send_message(msg, ephemeral=True)
# Command: Remove a Participant from an Event
@edit_group.command(name="remove", description="Remove a participant from an event.")
@app_commands.describe(
    event_title="The event to modify",
    member="The user to remove from the event"
)
async def remove_participant(
    interaction: discord.Interaction,
    event_title: str,
    member: discord.Member
):
    """
    Removes a participant from a specific event.

    Args:
        interaction (discord.Interaction): The interaction context.
        event_title (str): The title of the event.
        member (discord.Member): The participant to remove.
    """
    event_data = get_event_data(event_title)

    if not event_data:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only the host or an admin can remove participants.", ephemeral=True)
        return

    attendees = event_data["attendees"].split(", ") if event_data["attendees"] else []

    if member.mention not in attendees:
        await interaction.response.send_message(f"❌ {member.mention} is not a participant in '{event_title}'.", ephemeral=True)
        return

    attendees.remove(member.mention)
    updated_attendees = ", ".join(attendees)

    execute_query("UPDATE events SET attendees = ? WHERE title = ?", (updated_attendees, event_title))

    # Remove the role from the user
    role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])
    if role and role in member.roles:
        await member.remove_roles(role)

    # Refresh the event display
    channel = bot.get_channel(event_data["channel_id"])
    if channel:
        await display_event(channel, get_event_data(event_title))

    await interaction.response.send_message(f"✅ {member.mention} has been removed from **'{event_title}'**.", ephemeral=True)
    
# Shared Autocomplete for Edit Commands
@remove_participant.autocomplete("event_title")
@edit_max.autocomplete("event_title")
@edit_time.autocomplete("event_title")
@edit_date.autocomplete("event_title")
@edit_description.autocomplete("event_title")
async def autocomplete_edit_titles(interaction: discord.Interaction, current: str):
    """
    Provides autocomplete suggestions for event titles when editing event properties.

    Args:
        interaction (discord.Interaction): The interaction context.
        current (str): The current input text to match against event titles.

    Returns:
        List[app_commands.Choice]: A list of matching event title choices.
    """
    return await autocomplete_event_titles(interaction, current)

@bot.event
async def on_ready():
    """Triggered when the bot is ready."""
    print(f'✅ Logged in as {bot.user}')
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)  # Sync instantly to just this server
    if not check_event_reminders.is_running():
        check_event_reminders.start()

    events = execute_query("SELECT title, host FROM events")
    for title, event_host in events:  # Renamed `host` to `event_host`
        bot.add_view(ParticipationView(title, event_host))

    print("🎭 Persistent views registered for active events.")
    await tree.sync()
    print("✅ Slash commands synced!")

try:
    bot.run(TOKEN)
except discord.errors.LoginFailure:
    print("❌ Invalid bot token! Check your `config.json` and ensure the token is correct.")
