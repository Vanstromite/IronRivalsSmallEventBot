# Discord Event Management Bot

This bot helps manage events within a Discord server. It allows users to create, join, leave, and mark events as completed. The bot also sends reminders for upcoming events and updates event statuses (Upcoming, Ongoing, Completed).

## Features:
- Event creation with role assignment.
- Users can join or leave events with role management.
- Sends reminders for upcoming events.
- Updates event status (Upcoming, Ongoing, Completed).
- Allows host transfer functionality.
- Admin can delete all events and related roles/messages.

## Requirements

- Python 3.8 or higher
- Discord.py library
- SQLite3 database (events.db)
- `config.json` file with your Discord bot's token
```
{
    "TOKEN": "put your discord token here"
}
```
## Installation

Follow these steps to install and run the bot:
```
pip install -r requirements.txt

python eventbot.py
```
## Commands

- !host <event_title> <DD_MM_YYYY> <HH:MM> <description>: Create a new event.
- !join <event_title>: Join an event.
- !leave <event_title>: Leave an event.
- !complete <event_title>: Mark the event as completed (host/admin only).
- !transferhost <new_host> <event_title>: Transfer the event host to another user.
- !deleteallevents: Delete all events and their associated roles/messages (admin only).
- !list_commands: List all available commands.

