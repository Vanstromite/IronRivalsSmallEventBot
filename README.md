# Discord Event Management Bot

A Discord bot designed to make creating and managing events easy and interactive. Supports slash commands, role assignment, persistent buttons, event editing, reminders, and more.

---

## ✅ Features

- 🕵️ Slash command-based event creation  
- 🧠 Autocomplete for event names  
- 👥 Interactive join/leave buttons with automatic role assignment  
- 🎧 Host transfer between participants  
- ♻️ Real-time status updates: Upcoming → Ongoing  
- ⏰ 30-minute reminders before events  
- ✏️ Slash command editing for time, date, description, and participant cap  
- 🔒 Max attendee limits per event  
- 🧹 Admin tools to delete individual or all events  
- ❌ Host/Admin can remove participants from events  
- 💬 Slash command to list available commands  

---

## 📦 Requirements

- Python 3.8+
- `discord.py` v2.x (with app commands support)
- SQLite3
- `config.json` file with your bot token and guild ID:

- GUILD_ID is your discord server ID which admins can get by right clicking their server and selecting the option "Copy Server ID"
```json
{
  "TOKEN": "your-discord-bot-token",
  "GUILD_ID": 123456789012345678 
}
```
## 🛠️ Installation

Follow these steps to install and run the bot:
```
pip install -r requirements.txt

python eventbot.py
```
## 💬 Slash Commands

| Command              | Description                                               |
|----------------------|-----------------------------------------------------------|
| `/host`              | Create a new event with title, date, time, and description |
| `/transferhost`      | Transfer host role to another participant                 |
| `/deleteevent`       | Delete a specific event (host/admin only)                 |
| `/deleteallevents`   | Delete all events and roles/messages (admin only)         |
| `/edit time`         | Edit the event's time                                     |
| `/edit date`         | Edit the event's date                                     |
| `/edit description`  | Edit the event's description                              |
| `/edit max`          | Update the max number of participants                     |
| `/edit remove`       | Remove a participant from the event                       |
| `/commands`          | Show all available commands                               |


