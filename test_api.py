import requests
import json

API_URL = "http://localhost:8000/api/v1/optimize-schedule"

mock_payload = {
    "train_schedule": [
        {
            "train_no": "11448",
            "direction": "UP",
            "section_id": "HWH_to_BWN",
            "start_day": 1.0,
            "entry_time": "14:30:00",
            "end_day": 1.0,
            "exit_time": "15:53:00"
        },
        {
            "train_no": "11447",
            "direction": "DOWN",
            "section_id": "HWH_to_BWN",
            "start_day": 2.0,
            "entry_time": "02:37:00",
            "end_day": 2.0,
            "exit_time": "04:15:00"
        }
    ],
    "pending_tasks": [
        {"task_id": "ENG-1", "department": "Engineering", "tier": "Tier 1", "section_id": "HWH_to_BWN", "work_duration_mins": 180},
        {"task_id": "SIG-99", "department": "Signalling", "tier": "Tier 3", "section_id": "HWH_to_BWN", "work_duration_mins": 400} 
    ]
}

print("Sending translated data to Central Routing API...")
response = requests.post(API_URL, json=mock_payload)

if response.status_code == 200:
    print("\n✅ API Success! Backend response:")
    print(json.dumps(response.json(), indent=2))
else:
    print(f"\n❌ API Failed with status code {response.status_code}")
    print(response.text)