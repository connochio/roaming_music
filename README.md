[![Static Badge](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white)](https://github.com/hacs/integration) 
![GitHub Release](https://img.shields.io/github/v/release/connochio/roaming_music?style=for-the-badge&label=Current%20Release&color=41BDF5&cacheSeconds=15600)
![GitHub Issues or Pull Requests](https://img.shields.io/github/issues/connochio/roaming_music?style=for-the-badge)

# Roaming Music

A Home Assistant integration for making your music roam with you around your home.

> [!IMPORTANT]
> This integration is currently in the beta stage, and may have significant bugs.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=connochio&repository=roaming_music&category=Integration)

Install this integration via HACS with the link above.

<br />

## Setup

1. Install the integration from your integrations page
2. After installing, go to the integration and click 'Add device' to create a room
3. Give the room a name and submit
4. Click the cog icon on the newly created room, and set the speaker(s), presence sensors, room default volume and fade duration.
5. After clicking submit, select the presence sensor state that shows occupancy.

> [!IMPORTANT]
> In order for music to 'roam' currently, music must be playing on ***all*** speakers in all configured rooms.
> 
> This can be done via a Music Assistant player sync group