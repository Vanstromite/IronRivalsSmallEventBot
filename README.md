# Discord Event Management Bot

A fully interactive Discord bot for creating, managing, and participating in events — complete with role assignment, time-based reminders, embedded displays, and full slash command support.

---

## ✅ Features

- 🧾 **Event creation via modal forms** (no confusing parameters)
- 🧠 **Autocomplete** for event titles in commands
- 👥 **Join/Leave buttons** with auto role assignment
- 🔁 **Host transfer** to another participant
- ⏳ **Live countdowns** and automatic status updates: Upcoming → Ongoing → Completed
- ⏰ **30-minute reminders** before events start
- ✏️ **In-place editing**: time, date, description, cap, and more
- 🔒 **Max attendee limits** with open slot tracking
- 🔐 **Edit/delete restricted** to event hosts or server admins
- 🧹 **Admin tools**: delete all events, auto role cleanup
- 🌐 **Localized time support** (uses Discord's timestamp formatting)
- 💬 `/commands` to list all available features

---

## 📦 Requirements

- Python 3.8+
- `discord.py` v2.x (with `app_commands`)
- `sqlite3` (bundled with Python)
- `pytz`
- `config.json` file containing your bot token and guild ID

### `config.json` Example:
```json
{
  "TOKEN": "your-bot-token-here",
  "GUILD_ID": 123456789012345678
}
```
Tip: To get your Guild ID, enable Developer Mode in Discord and right-click your server name → "Copy Server ID".

## 🛠️ Installation

1. Clone this repository  
2. Create your `config.json`  
3. Install dependencies:

```bash
pip install -r requirements.txt
```
## 💬 Slash Commands

| Command              | Description                                                   |
|----------------------|---------------------------------------------------------------|
| `/host_event`        | Create a new event (via modal form)                           |
| `/transferhost`      | Transfer host role to another participant                     |
| `/deleteevent`       | Delete a specific event (host/admin only)                     |
| `/deleteallevents`   | Delete all events and roles/messages (admin only)             |
| `/edit time`         | Edit the time of an event                                     |
| `/edit date`         | Edit the date of an event                                     |
| `/edit description`  | Edit the event's description                                  |
| `/edit max`          | Edit the max number of participants                           |
| `/edit remove`       | Remove a participant from an event                            |
| `/commands`          | Show all available slash commands                             |


## 🧪 Database

All events are stored in a local `events.db` SQLite database. Events persist across restarts, and views/buttons are restored automatically.

