import os
from flask import Flask, render_template, request, url_for
from datetime import datetime
from weather_utils import (
    get_forecast,
    suggest_best_time_for_n_hours,
    generate_forecast_timeline,
)

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def home():
    suggestion = None
    timeline_url = None
    error = None
    form_data = {
        "city": "",
        "planned_datetime": "",
        "duration": "2",
    }

    if request.method == "POST":
        form_data["city"] = request.form.get("city", "").strip()
        form_data["planned_datetime"] = request.form.get("planned_datetime", "").strip()
        form_data["duration"] = request.form.get("duration", "2").strip()

        try:
            planned_dt = datetime.strptime(
                form_data["planned_datetime"], "%Y-%m-%d %H:%M"
            )
            duration = int(form_data["duration"])

            if not form_data["city"]:
                raise ValueError("Please enter a city.")
            if duration < 1 or duration > 12:
                raise ValueError("Duration must be between 1 and 12 hours.")
            if planned_dt.hour < 6 or planned_dt.hour >= 22:
                raise ValueError("Please choose a start time between 06:00 and 21:59.")
            if planned_dt.hour * 60 + planned_dt.minute + duration * 60 > 22 * 60:
                raise ValueError("The event must finish by 10:00 PM.")

            forecast = get_forecast(form_data["city"])
            if isinstance(forecast, dict) and forecast.get("error"):
                error = forecast["error"]
            else:
                result = suggest_best_time_for_n_hours(
                    forecast, form_data["planned_datetime"], duration
                )
                if isinstance(result, dict):
                    suggestion = result.get("message", str(result))
                else:
                    suggestion = result

                chart_path = generate_forecast_timeline( forecast, os.path.join(app.static_folder, "forecast_timeline.png"))
                if chart_path:
                    timeline_url = url_for("static", filename="forecast_timeline.png")

        except ValueError as exc:
            error = str(exc)

    return render_template(
        "index.html",
        suggestion=suggestion,
        timeline_url=timeline_url,
        error=error,
        form_data=form_data,
    )


if __name__ == "__main__":
    app.run(debug=True)
