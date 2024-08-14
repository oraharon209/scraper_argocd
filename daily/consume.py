from datetime import datetime, timedelta

# Example match_data startDate
match_start_date = "2024-06-20T14:00:00.000Z"

# Convert match_start_date to a datetime object
match_start_datetime = datetime.strptime(match_start_date, '%Y-%m-%dT%H:%M:%S.%fZ')

# Get the current time
current_time = datetime.now()

# Calculate the time difference
time_difference = current_time - match_start_datetime

# Format the time difference as HH:MM:SS
formatted_time_difference = str(time_difference).split(".")[0]

print(f"Time difference: {formatted_time_difference}")