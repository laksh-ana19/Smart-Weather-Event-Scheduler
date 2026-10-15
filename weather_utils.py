import os
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import requests

# Set your own OpenWeatherMap API key in the OPENWEATHER_API_KEY environment variable.
# Do not publish your API key in a public repository or report screenshot.
API_KEY = os.environ.get("OPENWEATHER_API_KEY", "YOUR_OPENWEATHER_API_KEY")

FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_forecast(city):
    """Return OpenWeatherMap's forecast entries (usually 5 days at 3-hour intervals)."""
    if not API_KEY or API_KEY == "YOUR_OPENWEATHER_API_KEY":
        return {"error": "Add your OpenWeatherMap API key before using the app."}

    try:
        response = requests.get(
            FORECAST_URL,
            params={"q": city, "appid": API_KEY, "units": "metric"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        if str(data.get("cod")) != "200":
            return {"error": data.get("message", f"Could not find forecast for {city}.")}

                # dt_txt is in UTC; convert to the city's local time using its UTC offset.
        offset_seconds = data.get("city", {}).get("timezone", 0)
        offset = timedelta(seconds=offset_seconds)

        forecast_list = []
        for entry in data.get("list", []):
            utc_time = datetime.fromtimestamp(entry["dt"], timezone.utc).replace(tzinfo=None)
            local_time = utc_time + offset
            forecast_list.append({
                "datetime": local_time.strftime(DATETIME_FORMAT),
                "utc_offset": offset_seconds,
                "temperature": entry["main"]["temp"],
                "humidity": entry["main"]["humidity"],
                "description": entry["weather"][0]["description"].title(),
                "rain": entry.get("pop", 0) * 100,
            })
        return forecast_list

    except requests.RequestException as exc:
        return {"error": f"Could not contact the weather service: {exc}"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Could not read the forecast response: {exc}"}


def _parse_forecast_time(entry):
    return datetime.strptime(entry["datetime"], DATETIME_FORMAT)


def _is_suitable(entry):
    """Basic outdoor-event rule; tune these thresholds to suit your campus."""
    description = entry.get("description", "").lower()
    temperature = entry.get("temperature", 0)
    rain_chance = entry.get("rain", 0)
    bad_words = ("rain", "storm", "snow", "thunder")
    return (
        not any(word in description for word in bad_words)
        and rain_chance <= 50
        and temperature <= 34
        and temperature >= 5
    )


def suggest_best_time_for_n_hours(forecast_data, planned_start_str, duration_hours):
    """
    Check the planned slot, then search the available forecast within one day
    before/after the chosen date. Events must start at/after 06:00 and finish
    by 22:00. OpenWeatherMap forecasts are spaced 3 hours apart, so results
    are estimates rather than exact hourly predictions.
    """
    if isinstance(forecast_data, dict) and forecast_data.get("error"):
        return forecast_data["error"]
    if not forecast_data:
        return "No forecast data is available for this city."

    try:
        planned_start = datetime.strptime(planned_start_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return "Enter the start date and time as YYYY-MM-DD HH:MM (24-hour clock)."

    try:
        duration_hours = int(duration_hours)
    except (TypeError, ValueError):
        return "Duration must be a whole number of hours."

    if duration_hours < 1 or duration_hours > 12:
        return "Duration must be between 1 and 12 hours."
    if planned_start.hour < 6 or planned_start.hour >= 22:
        return "Choose an event start time between 06:00 and 21:59."
    if planned_start + timedelta(hours=duration_hours) > planned_start.replace(
        hour=22, minute=0, second=0
    ):
        return "The event must finish by 10:00 PM."

    entries = sorted(
        [( _parse_forecast_time(item), item) for item in forecast_data],
        key=lambda pair: pair[0],
    )
        # "Now" in the city's local time, not the computer's time zone.
    offset = timedelta(seconds=forecast_data[0].get("utc_offset", 0))
    now = datetime.now(timezone.utc).replace(tzinfo=None) + offset
    last_time = entries[-1][0]

    if planned_start + timedelta(hours=duration_hours) <= now:
        return "That time has already passed. Please choose a future start time."
    if planned_start > last_time + timedelta(hours=3):
        return (
            f"The forecast only covers up to {last_time:%Y-%m-%d %H:%M}. "
            f"Please choose a date within the next 5 days."
        )
    # Only search dates within +/- 1 day and never suggest a time in the past.
    search_start = (planned_start - timedelta(days=1)).replace(
        hour=6, minute=0, second=0
    )
    search_end = (planned_start + timedelta(days=1)).replace(
        hour=22, minute=0, second=0
    )

    def nearest_entry(target):
        return min(entries, key=lambda pair: abs((pair[0] - target).total_seconds()))[1]

    def slot_weather(start):
        # Forecast samples are 3 hours apart; inspect each sample falling in
        # the requested duration, using the nearest available forecast sample.
        checked = []
        for offset in range(0, duration_hours, 3):
            checked.append(nearest_entry(start + timedelta(hours=offset)))
        return checked

    planned_samples = slot_weather(planned_start)
    planned_ok = all(_is_suitable(item) for item in planned_samples)
    planned_summary = []
    for item in planned_samples:
        planned_summary.append(
            f"{item['description'].lower()}, {item['temperature']:.1f}°C, "
            f"{item.get('rain', 0):.0f}% chance of rain"
        )
    weather_text = "; ".join(planned_summary)

    if planned_ok:
        return (
            f"Planned slot: {planned_start:%Y-%m-%d %H:%M} for {duration_hours} hour(s). "
            f"Forecast: {weather_text}. Conditions look suitable based on the available forecast."
        )

    # Candidate starts are aligned to the forecast's 3-hour sampling intervals.
    candidates = []
    for entry_time, entry in entries:
        if entry_time < now or entry_time < search_start or entry_time > search_end:
            continue
        if not (6 <= entry_time.hour < 22):
            continue
        end_time = entry_time + timedelta(hours=duration_hours)
        if end_time.date() != entry_time.date() or end_time > entry_time.replace(
            hour=22, minute=0, second=0
        ):
            continue
        if entry_time < search_start or entry_time > search_end:
            continue

        samples = slot_weather(entry_time)
        if all(_is_suitable(item) for item in samples):
            distance = abs((entry_time - planned_start).total_seconds())
            candidates.append((distance, entry_time, end_time, entry, samples))

    if candidates:
        _, start, end, first_entry, samples = min(candidates, key=lambda item: item[0])
        sample_summary = "; ".join(
            f"{item['description'].lower()}, {item['temperature']:.1f}°C, "
            f"{item.get('rain', 0):.0f}% chance of rain"
            for item in samples
        )
        return (
            f"Your planned slot may not be suitable. Forecast during that time: {weather_text}. "
            f"Suggested alternative: {start:%Y-%m-%d %H:%M} to {end:%H:%M} "
            f"({duration_hours} hour(s)). Forecast: {sample_summary}. "
            f"This is the closest suitable slot found within one day before or after your date."
        )

    return (
        f"The planned slot may not be suitable. Forecast during that time: {weather_text}. "
        f"No suitable {duration_hours}-hour slot was found in the available forecast "
        f"within one day before or after your chosen date, between 6:00 AM and 10:00 PM. "
        f"The weather service provides forecast samples every 3 hours, so try checking again later."
    )


def generate_forecast_timeline(forecast_list, save_path="static/forecast_timeline.png"):
    """Save a color-coded overview chart and return its relative file path."""
    if not forecast_list or (isinstance(forecast_list, dict) and forecast_list.get("error")):
        return None

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    times = [_parse_forecast_time(item) for item in forecast_list]
    colors = []
    for item in forecast_list:
        if not _is_suitable(item):
            colors.append("red")
        elif item.get("temperature", 0) > 30 or item.get("rain", 0) > 20:
            colors.append("gold")
        else:
            colors.append("green")

    fig, ax = plt.subplots(figsize=(12, 3))
    ax.bar(times, [1] * len(times), width=0.10, color=colors, align="center",
           edgecolor="white", linewidth=0.5)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    ax.set_yticks([])
    ax.set_title("Five-Day Weather Forecast (3-hour intervals)")
    ax.set_xlabel("Forecast date and time")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(save_path, dpi=140)
    plt.close(fig)
    return save_path.replace("\\", "/")
