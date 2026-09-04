import requests
import json
import time

BASE_URL = "http://localhost:8000/api/v1"

# The input payload remains identical to the frontend's requirement.
# Do NOT send a secret ID here; the backend must generate it.
mock_payload = {
    "train_schedule": [
        {"train_no": "11448", "direction": "UP", "SectionID": "HWH_to_BWN", "start_day": 1.0, "entry_time": "14:30:00", "end_day": 1.0, "exit_time": "15:53:00"},
        {"train_no": "11447", "direction": "DOWN", "SectionID": "HWH_to_BWN", "start_day": 2.0, "entry_time": "02:37:00", "end_day": 2.0, "exit_time": "04:15:00"}
    ],
    "pending_tasks": [
        {
            "task-id": "TMS-1", 
            "department": "TMS", 
            "SectionID": "HWH_to_BWN", 
            "date": "2026-09-03T10:00:00Z", 
            "maintenance_frequency": "special",
            "work_duration_mins": 180
        }
    ]
}

mock_rule = {
    "task-id": "TDMS-1",
    "department": "TDMS",
    "SectionID": "HWH_to_BWN",
    "date": "2026-08-27T10:00:00Z",
    "maintenance_frequency": "weekly",
    "work_duration_mins": 120
}

print("☀️  [DAYTIME] Submitting ad-hoc 'special' requests...")
requests.post(f"{BASE_URL}/submit-tasks", json=mock_payload)

print("⚙️  [MANAGEMENT] Adding a 'weekly' routine maintenance plan...")
requests.post(f"{BASE_URL}/add-recurring-rule", json=mock_rule)

time.sleep(2) 

print("\n🌙 [MIDNIGHT] Triggering the 12:30 AM batch processor...")
batch_response = requests.post(f"{BASE_URL}/trigger-batch-run")

print("\n✅ Batch Job Success! Final Output Verification:")
response_data = batch_response.json()
print(json.dumps(response_data, indent=2))

# --- VERIFICATION LOOP ---
print("\n🔍 Verifying Backend Secret IDs:")
if "scheduled_tasks" in response_data:
    for task in response_data["scheduled_tasks"]:
        secret_id = task.get("secret_id", "MISSING_ID")
        print(f"Task {task.get('task-id')} -> Secret Backend ID: {secret_id}")
else:
    print("No tasks were returned by the backend.")
