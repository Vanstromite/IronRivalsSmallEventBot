import re
import sqlite3
from datetime import datetime, timedelta, timezone
import json
import pytz
import discord
from discord.ext import commands, tasks



# Bot setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

def execute_query(query, params=()):
    """Executes a query with proper connection handling."""
    with sqlite3.connect("events.db") as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.fetchall()

def setup_database():
    """Creates the events table if it doesn't already exist and adds the 'status' column."""
    with sqlite3.connect("events.db") as connection:
        cursor = connection.cursor()

        # ✅ Ensure the events table has a 'status' column
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
            status TEXT DEFAULT 'Upcoming'  -- ✅ New column to store event status
        )
        """)
        connection.commit()

setup_database()

@tasks.loop(minutes=1)
async def check_event_reminders():
    """Checks if events are happening soon, updates statuses, and sends reminders."""
    # Use timezone-aware UTC time
    current_time = datetime.now(timezone.utc)  # Current UTC time (timezone-aware)
    future_time = current_time + timedelta(minutes=30)  # Time 30 minutes from now
    future_time_str = future_time.strftime("%H:%M UTC")  # Format future time for comparison

    sent_reminders = set()  # Prevent duplicate reminders

    # ✅ Send 30-minute reminders
    events_near = execute_query("SELECT title FROM events WHERE time = ?", (future_time_str,))

    for (title,) in events_near:
        event_data = get_event_data(title)  # Fetch latest event details
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

    # ✅ Find events transitioning to "Ongoing" based on event date and time
    events_to_update = execute_query("SELECT title, date, time FROM events WHERE status = 'Upcoming'")

    for title, event_date, event_time in events_to_update:
        event_data = get_event_data(title)
        if not event_data:
            continue

        # Combine date and time to create full event start datetime
        event_start_str = f"{event_date} {event_time}"  # Combine the date and time
        print(f"Event start string: {event_start_str}")  # Debugging line

        try:
            # Make event start time timezone-aware by adding UTC timezone
            event_start_time = datetime.strptime(event_start_str, "%d-%m-%Y %H:%M UTC").replace(tzinfo=timezone.utc)
        except ValueError as e:
            print(f"Error parsing event start time: {e}")
            continue

        # Get current UTC date and time for comparison
        current_time_obj = datetime.now(timezone.utc)  # Use timezone-aware current time
        print(f"Current time: {current_time_obj}")  # Debugging line

        # Check if the event start time has passed (compare both date and time)
        if current_time_obj >= event_start_time:
            # ✅ If current time >= event start time, mark the event as "Ongoing"
            print(f"Event '{title}' is now transitioning to Ongoing")
            execute_query("UPDATE events SET status = 'Ongoing' WHERE title = ?", (title,))

            # ✅ Update event data status
            event_data["status"] = "Ongoing"

            # ✅ Send a ping message to notify members that the event has started
            channel = bot.get_channel(event_data["channel_id"])
            if channel:
                role = discord.utils.get(channel.guild.roles, id=event_data["role_id"])
                if role:
                    await channel.send(f"🚀 <@&{role.id}>, **'{title}'** has now **started!** 🎉")

            # ✅ Update event embed dynamically
            await display_event(channel, event_data)


def get_event_data(title):
    """Fetches event details from the database and returns as a dictionary."""
    event = execute_query("SELECT title, date, time, description, attendees, message_id, role_id, channel_id, host, status FROM events WHERE title = ?", (title,))
    
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
        "status": event[9]
    }


async def display_event(ctx, event_data):
    """Displays or updates an event embed using event_data dictionary."""
    embed = discord.Embed(title=f"📅 {event_data['title']}", description=event_data['description'], color=discord.Color.blue())

    # ✅ Convert event time (which is in UTC) to desired format (e.g., 19:00 02/23/2025)
    event_time_utc = datetime.strptime(event_data['time'], "%H:%M UTC")

    # Format the time as HH:mm (gametime)
    formatted_time = event_time_utc.strftime("%H:%M")

    # ✅ Convert event date from DD-MM-YYYY to MM/DD/YYYY and make it aware
    event_date = datetime.strptime(event_data['date'], "%d-%m-%Y")  # Use '-' as separator
    event_date = event_date.replace(tzinfo=timezone.utc)  # Make it UTC-aware
    formatted_date = event_date.strftime("%m/%d/%Y")  # Format it as MM/DD/YYYY

    # ✅ Calculate the relative date
    current_time = datetime.now(timezone.utc)  # Current time in UTC (aware datetime)
    days_difference = (event_date.date() - current_time.date()).days  # Compare only the date (not time)

    # Display the event date with the correct relative time
    if days_difference == 0:
        relative_date = "TODAY"
    elif days_difference > 0:
        relative_date = f"In {days_difference} days"
    else:
        relative_date = f"{abs(days_difference)} days ago"

    # ✅ Display event status
    status_display = {
        "Upcoming": "🟢 Upcoming",
        "Ongoing": "🟡 Ongoing",
        "Completed": "🔴 Completed"
    }.get(event_data["status"], "❓ Unknown")

    embed.add_field(name="📌 Status", value=status_display, inline=False)
    embed.add_field(name="🎤 Host", value=event_data["host"], inline=False)  # ✅ Keep host separate
    embed.add_field(name="📅 Date", value=f"{formatted_date} ({relative_date})", inline=False)  # ✅ Display formatted date with relative time
    embed.add_field(name="🕒 Time", value=f"{formatted_time} (gametime)", inline=False)  # ✅ Updated format

    # ✅ Ensure proper formatting of participants list
    attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []

    # ✅ Ensure the host is always listed first
    if event_data["host"] not in attendees_list:
        attendees_list.insert(0, event_data["host"])

    formatted_attendees = ", ".join(attendees_list) if attendees_list else "No participants yet"

    embed.add_field(name="✅ Participants", value=formatted_attendees, inline=False)
    embed.set_footer(text="Click a button below to join, leave, or complete the event!")

    view = ParticipationView(event_data["title"], event_data["host"])  # ✅ Ensure buttons persist
    bot.add_view(view)  # ✅ Register the view

    if event_data["message_id"]:
        try:
            message = await ctx.fetch_message(int(event_data["message_id"]))
            await message.edit(embed=embed, view=view)
            return message
        except discord.NotFound:
            return await ctx.send(embed=embed, view=view)
    else:
        return await ctx.send(embed=embed, view=view)  # ✅ Single return!


class ParticipationView(discord.ui.View):
    """Interactive view with Join, Leave, and Complete buttons for event participation."""
    def __init__(self, event_title, host):
        super().__init__(timeout=None)  # ✅ Persistent view
        self.event_title = event_title
        self.host = host  # ✅ Track event host
        self.add_item(ParticipateButton(event_title))
        self.add_item(LeaveButton(event_title))
        self.add_item(CompleteEventButton(event_title, host))  # ✅ New Complete Event button

    async def interaction_check(self, interaction: discord.Interaction) -> bool:  # ✅ Fix: Add `interaction` parameter
        """Ensures the interaction is still valid (fixes 'This interaction failed' errors)."""
        return True  # ✅ Allows interactions even after a restart

class CompleteEventButton(discord.ui.Button):
    """Button to allow the event host or an admin to mark an event as completed."""
    def __init__(self, event_title, host):
        super().__init__(label="Complete Event", style=discord.ButtonStyle.danger, custom_id=f"complete_{event_title}")
        self.event_title = event_title
        self.host = host  # ✅ Track the event host

    async def callback(self, interaction: discord.Interaction):
        """Handles event completion when pressed by the host or an admin."""
        event_data = get_event_data(self.event_title)  # ✅ Fetch latest event details

        if not event_data:
            await interaction.response.send_message(f"❌ No event found with the title: `{self.event_title}`", ephemeral=True)
            return

        # ✅ Ensure only the host or admin can complete the event
        if interaction.user.mention != event_data["host"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only the event host or an admin can complete this event.", ephemeral=True)
            return

        # ✅ Update the database to mark the event as completed
        execute_query("UPDATE events SET status = 'Completed' WHERE title = ?", (self.event_title,))

        # ✅ Remove the event role from the host and participants
        role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])
        if role:
            # Remove role from host
            host_member = discord.utils.get(interaction.guild.members, mention=event_data["host"])
            if host_member:
                await host_member.remove_roles(role)
                print(f"🗑 Removed event role from host: {event_data['host']}")

            # Remove role from participants
            attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []
            for participant in attendees_list:
                participant_member = discord.utils.get(interaction.guild.members, mention=participant)
                if participant_member:
                    await participant_member.remove_roles(role)
                    print(f"🗑 Removed event role from participant: {participant}")

            # ✅ Check if the role is empty and delete it
            if not role.members:
                await role.delete()
                execute_query("UPDATE events SET role_id = NULL WHERE title = ?", (self.event_title,))
                print(f"🗑 Deleted empty role: {role.name}")

        # ✅ Send a thank you message in the event channel
        channel = bot.get_channel(event_data["channel_id"])  # ✅ Fetch channel where the event occurred
        if channel:
            role = discord.utils.get(channel.guild.roles, id=event_data["role_id"])
            if role:
                # Send thank you message to participants
                await channel.send(f"🎉 **Thank you for participating in '{self.event_title}'!** 🎉\n"
                                   f"<@&{role.id}>, this event has now concluded.")

            # ✅ Remove the join/leave buttons after completion
            await display_completed_event(channel, event_data)

        # ✅ Clear event entry from the database to allow new events with the same name
        execute_query("DELETE FROM events WHERE title = ?", (self.event_title,))

        await interaction.response.send_message(f"✅ Event **'{self.event_title}'** has been marked as **Completed**!", ephemeral=True)

async def display_completed_event(ctx, event_data):
    """Displays the final event embed after completion (buttons removed)."""
    embed = discord.Embed(title=f"📅 {event_data['title']}", description=event_data['description'], color=discord.Color.red())

    # ✅ Convert event time (which is in UTC) to desired format (e.g., 19:00 02/23/2025)
    event_time_utc = datetime.strptime(event_data['time'], "%H:%M UTC")

    # Format the time as HH:mm (gametime)
    formatted_time = event_time_utc.strftime("%H:%M")

    # ✅ Convert event date from DD-MM-YYYY to MM/DD/YYYY
    event_date = datetime.strptime(event_data['date'], "%d-%m-%Y")  # Use '-' as separator
    formatted_date = event_date.strftime("%m/%d/%Y")  # Format it as MM/DD/YYYY

    # ✅ Calculate the number of days since the event ended
    current_time = datetime.utcnow()
    days_since_event = (current_time - event_date).days

    # If the event is completed today
    if days_since_event == 0:
        date_display = f"{formatted_date} (this event concluded today)"
    elif days_since_event > 0:
        date_display = f"{formatted_date} (this event concluded {days_since_event} day{'s' if days_since_event > 1 else ''} ago)"
    else:
        date_display = formatted_date  # If for some reason the event date is in the future (edge case)

    # ✅ Display event status
    embed.add_field(name="📌 Status", value="🔴 Completed", inline=False)
    embed.add_field(name="🎤 Host", value=event_data["host"], inline=False)
    embed.add_field(name="📅 Date", value=date_display, inline=False)  # ✅ Display formatted date and days ago
    embed.add_field(name="🕒 Time", value=f"{formatted_time} (gametime)", inline=False)  # ✅ Updated format

    # ✅ List final participants
    attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []
    formatted_attendees = ", ".join(attendees_list) if attendees_list else "No participants"

    embed.add_field(name="✅ Final Participants", value=formatted_attendees, inline=False)
    embed.set_footer(text="This event has now concluded. Thank you for participating!")

    # ✅ Remove the buttons by sending the embed without a view
    if event_data["message_id"]:
        try:
            message = await ctx.fetch_message(int(event_data["message_id"]))
            await message.edit(embed=embed, view=None)  # ✅ Remove buttons
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
        event_data = get_event_data(self.event_title)  # ✅ Fetch latest event details

        if not event_data:
            await interaction.response.send_message(f"❌ No event found with the title: `{self.event_title}`", ephemeral=True)
            return

        attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []

        # ✅ Prevent duplicate joins
        if interaction.user.mention in attendees_list:
            await interaction.response.send_message("❌ You are already participating!", ephemeral=True)
            return

        attendees_list.append(interaction.user.mention)  # ✅ Add user to attendees
        formatted_attendees = ", ".join(attendees_list)  # ✅ Ensure proper formatting

        # ✅ Update database
        execute_query("UPDATE events SET attendees = ? WHERE title = ?", (formatted_attendees, self.event_title))

        # ✅ Assign role if needed
        role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])
        if role:
            await interaction.user.add_roles(role)

        # ✅ Update event embed dynamically
        event_data["attendees"] = formatted_attendees  # ✅ Update event data locally
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
        event_data = get_event_data(self.event_title)  # ✅ Fetch latest event details

        if not event_data:
            await interaction.response.send_message(f"❌ No event found with the title: `{self.event_title}`", ephemeral=True)
            return

        attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []

        # ✅ Prevent the host from fully leaving the event
        if interaction.user.mention == event_data["host"]:
            await interaction.response.send_message("❌ The host cannot leave the event.", ephemeral=True)
            return

        if interaction.user.mention in attendees_list:
            attendees_list.remove(interaction.user.mention)

            # ✅ Update database with new attendees list
            execute_query("UPDATE events SET attendees = ? WHERE title = ?", (", ".join(attendees_list), self.event_title))

            # ✅ Remove the event role
            role = discord.utils.get(interaction.guild.roles, id=event_data["role_id"])
            if role:
                await interaction.user.remove_roles(role)

                # ✅ Delete role only if no one else has it
                if not role.members:
                    await role.delete()
                    execute_query("UPDATE events SET role_id = NULL WHERE title = ?", (self.event_title,))
                    print(f"🗑 Deleted empty role: {role.name}")

            # ✅ Fetch updated event details
            event_data["attendees"] = ", ".join(attendees_list)  # ✅ Update event data locally

            # ✅ Update event embed dynamically
            channel = bot.get_channel(event_data["channel_id"])
            if channel:
                await display_event(channel, event_data)

            await interaction.response.send_message(f"❌ {interaction.user.mention} has left the event.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You are not in this event!", ephemeral=True)

@bot.command()
async def transferhost(ctx, new_host: discord.Member, *, event_title: str):
    """Transfers the event host role to another participant in a specific event."""
    # ✅ Get the event details from the database using the event title
    event_data = get_event_data(event_title)

    if not event_data:
        await ctx.send(f"❌ No event found with the title '{event_title}'. Please check the title and try again.")
        return

    # ✅ Ensure the current user is the host or an admin
    if ctx.author.mention != event_data["host"] and not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You must be the current host or an admin to transfer the host role.")
        return

    # ✅ Check if the new host is a valid participant
    attendees_list = event_data["attendees"].split(", ") if event_data["attendees"] else []

    if new_host.mention not in attendees_list:
        await ctx.send(f"❌ {new_host.mention} is not a participant in the event '{event_title}'!")
        return

    # ✅ Remove the role from the old host (if they are no longer the host)
    old_host = discord.utils.get(ctx.guild.members, mention=event_data["host"])
    if old_host:
        role = discord.utils.get(ctx.guild.roles, id=event_data["role_id"])
        if role:
            await old_host.remove_roles(role)
            print(f"🗑 Removed role from old host: {event_data['host']}")

    # ✅ Update the host in the database
    execute_query("UPDATE events SET host = ? WHERE title = ?", (new_host.mention, event_title))

    # ✅ Ensure the role is assigned to the new host
    role = discord.utils.get(ctx.guild.roles, id=event_data["role_id"])
    if role:
        # Check if the new host already has the role
        if role not in new_host.roles:
            await new_host.add_roles(role)
            print(f"✅ Assigned event role to the new host: {new_host.mention}")
        else:
            print(f"✅ New host already has the role: {new_host.mention}")

    # ✅ Send a confirmation message
    await ctx.send(f"✅ The host role for event '{event_title}' has been transferred to {new_host.mention}!")

    # ✅ Update event embed to reflect the new host
    event_data["host"] = new_host.mention  # ✅ Update the event data
    channel = bot.get_channel(event_data["channel_id"])
    if channel:
        await display_event(channel, event_data)



@bot.command()
async def purge_roles(ctx):
    """Removes all event-related roles from the user."""
    user = ctx.author
    event_roles = execute_query("SELECT role_id FROM events")

    removed_roles = []
    for role_id in event_roles:
        role = discord.utils.get(ctx.guild.roles, id=role_id[0])  # Extract role_id tuple
        if role and role in user.roles:
            await user.remove_roles(role)
            removed_roles.append(role.name)

    if removed_roles:
        await ctx.send(f"✅ Removed event roles: {', '.join(removed_roles)}")
    else:
        await ctx.send("✅ No event roles to remove.")

@bot.command()
async def host(ctx, *, args: str = None):
    """Creates a new event, assigns a custom role, and displays it with participation buttons."""
    # Check if no args are provided
    if not args:
        await ctx.send("❌ Usage: `!host <event_title> <DD_MM_YYYY> <HH:MM> <description>`")
        return

    try:
        print(f"Raw args received: {args}")

        # Regex to find date pattern (DD_MM_YYYY or DD-MM-YYYY)
        date_pattern = re.compile(r'\d{2}[-_]\d{2}[-_]\d{4}')
        parts = args.split()
        
        # Ensure there are enough parts for title, date, time, and description
        if len(parts) < 4:
            await ctx.send("❌ Usage: `!host <event_title> <DD_MM_YYYY> <HH:MM> <description>`")
            return

        date_index = next((i for i, part in enumerate(parts) if date_pattern.fullmatch(part)), -1)

        if date_index == -1 or date_index + 2 >= len(parts):
            await ctx.send("❌ Invalid date or time format. Ensure it's `DD_MM_YYYY` or `DD-MM-YYYY` for date and `HH:MM` for time.")
            return

        title = " ".join(parts[:date_index])
        date = parts[date_index]
        time = parts[date_index + 1]
        description = " ".join(parts[date_index + 2:]) if date_index + 2 < len(parts) else "Event description not provided"

        # Validate and format date/time
        try:
            event_date = datetime.strptime(date, "%d-%m-%Y").strftime("%d-%m-%Y")
            utc_time = datetime.strptime(time, "%H:%M").replace(tzinfo=pytz.utc)
        except ValueError:
            await ctx.send("❌ Invalid date or time format. Please ensure it's `DD_MM_YYYY` or `DD-MM-YYYY` for date and `HH:MM` for time.")
            return

        # Check if event already exists
        if get_event_data(title):
            await ctx.send(f"❌ An event with the title '{title}' already exists. Please choose a different title.")
            return

        # Create a role for the event, prepend "Event" to the role name
        role_name = f"Event {title}"  # Add "Event" before the event title to make it unique
        role = await ctx.guild.create_role(name=role_name)

        # ✅ Get the event host (creator) and automatically add them as a participant
        host = ctx.author.mention
        attendees = host  # ✅ Host is the first participant

        # ✅ Insert event into the database
        execute_query(
            """INSERT INTO events (title, date, time, description, attendees, message_id, role_id, channel_id, host, status) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, event_date, utc_time.strftime("%H:%M UTC"), description, attendees, "", role.id, ctx.channel.id, host, "Upcoming")
        )

        # ✅ Fetch updated event details
        event_data = get_event_data(title)

        # ✅ Add host to role
        await ctx.author.add_roles(role)

        # ✅ Create event embed and display it
        if event_data:
            message = await display_event(ctx, event_data)
            execute_query("UPDATE events SET message_id = ? WHERE title = ?", (str(message.id), title))

        await ctx.send(f"✅ Event **'{title}'** has been created successfully! Hosted by {host}")

    except ValueError as e:
        print(f"❌ ValueError: {e}")
        await ctx.send("❌ Invalid date or time format. Use `DD_MM_YYYY` for date and `HH:MM` for time.")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to create roles. Please check my permissions.")
    except discord.HTTPException as e:
        print(f"❌ Discord API Error: {e}")
        await ctx.send("❌ An error occurred while creating the role or event. Please try again.")
    except Exception as e:
        print(f"⚠️ Unexpected Error: {e}")
        await ctx.send("⚠️ An unexpected error occurred while creating the event. Please try again.")


@bot.command()
@commands.has_permissions(administrator=True)  # ✅ Restrict to admins
async def deleteallevents(ctx):
    """Deletes all events, removes associated roles, and clears event messages."""
    events = execute_query("SELECT title, role_id, message_id, channel_id FROM events")

    if not events:
        await ctx.send("✅ No events found to delete.")
        return

    deleted_roles = []
    deleted_messages = 0

    for title, role_id, message_id, channel_id in events:
        # ✅ Delete event role if it exists
        role = discord.utils.get(ctx.guild.roles, id=role_id)
        if role:
            await role.delete()
            deleted_roles.append(role.name)

        # ✅ Only attempt to delete the message if message_id is not empty
        if message_id:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    message = await channel.fetch_message(int(message_id))
                    await message.delete()
                    deleted_messages += 1
                except (discord.NotFound, discord.Forbidden):
                    pass  # Skip if message doesn't exist or bot lacks permission

        # ✅ Clear events from the database
        execute_query("DELETE FROM events")

    # ✅ Send confirmation message
    response = "✅ All events have been deleted.\n"
    if deleted_roles:
        response += f"🗑 Deleted roles: {', '.join(deleted_roles)}\n"
    response += f"🗑 Deleted messages: {deleted_messages}"

    await ctx.send(response)



# Load config.json safely with encoding
try:
    with open("config.json", "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    TOKEN = config["TOKEN"]
except (FileNotFoundError, json.JSONDecodeError):
    print("❌ Error: `config.json` is missing or invalid. Ensure it exists and is formatted correctly.")
    exit(1)

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')

    if not check_event_reminders.is_running():
        check_event_reminders.start()

    # ✅ Register views for all existing events
    events = execute_query("SELECT title, host FROM events")  # ✅ Fetch both title and host
    for title, host in events:
        bot.add_view(ParticipationView(title, host))  # ✅ Pass both title and host

    print("🎭 Persistent views registered for active events.")


try:
    bot.run(TOKEN)
except discord.errors.LoginFailure:
    print("❌ Invalid bot token! Check your `config.json` and ensure the token is correct.")
