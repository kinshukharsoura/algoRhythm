from ortools.sat.python import cp_model
from datetime import datetime
import json

def iso_to_epoch(iso_str):
    """Converts a timestamp like '2026-09-01T15:55:00Z' to integer seconds."""
    # Replace 'Z' with '+00:00' to ensure compatibility with Python's fromisoformat
    clean_str = iso_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_str)
    return int(dt.timestamp())

def epoch_to_iso(epoch_int):
    """Converts integer seconds back into a readable ISO timestamp with 'Z'."""
    # Convert back to UTC string format to match Team A's database
    dt = datetime.utcfromtimestamp(epoch_int)
    return dt.isoformat() + "Z"

def find_largest_corridor(train_schedule, section_id):
    """Calculates the largest train-free gap on a specific track section."""
    # Filter trains by the requested section
    section_trains = [t for t in train_schedule if t["section_id"] == section_id]
    
    if not section_trains:
        return None, None

    # Sort trains chronologically by their entry time
    section_trains.sort(key=lambda x: iso_to_epoch(x["corridor_entry_time"]))
    
    max_gap = 0
    best_start = None
    best_end = None
    
    # Find the largest time gap between the exit of one train and entry of the next
    for i in range(len(section_trains) - 1):
        current_exit = iso_to_epoch(section_trains[i]["corridor_exit_time"])
        next_entry = iso_to_epoch(section_trains[i+1]["corridor_entry_time"])
        
        gap = next_entry - current_exit
        if gap > max_gap:
            max_gap = gap
            best_start = section_trains[i]["corridor_exit_time"]
            best_end = section_trains[i+1]["corridor_entry_time"]
            
    return best_start, best_end

def generate_schedule(task_list, corridor_start_iso, corridor_end_iso):
    model = cp_model.CpModel()
    task_vars = {}
    
    corridor_start = iso_to_epoch(corridor_start_iso)
    corridor_end = iso_to_epoch(corridor_end_iso)
    
    # Railway Rule: All work must stop 15 minutes (900 seconds) before trains resume
    safe_corridor_end = corridor_end - 900 

    for task in task_list:
        # 1. Update keys to match Team A's database
        task_id = task["task_id"]
        duration_sec = task["work_duration_mins"] * 60 
        
        # 2. Convert string Tiers to mathematical integer priorities
        tier = task.get("tier", "Tier 3")
        if tier == "Tier 1":
            priority = 100
        elif tier == "Tier 2":
            priority = 70
        else:
            priority = 40
            
        is_scheduled = model.NewBoolVar(f'{task_id}_is_present')
        start = model.NewIntVar(corridor_start, safe_corridor_end, f'{task_id}_start')
        end = model.NewIntVar(corridor_start, safe_corridor_end, f'{task_id}_end')
        
        interval = model.NewOptionalIntervalVar(
            start, duration_sec, end, is_scheduled, f'{task_id}_interval'
        )
        
        task_vars[task_id] = {
            "start": start, "end": end, "interval": interval, 
            "is_scheduled": is_scheduled, "priority": priority,
            "dept": task["department"]
        }

    # 3. Map shadow blocking to Team A's department names
    eng_intervals = [var["interval"] for var in task_vars.values() if var["dept"] == "Engineering"]
    trac_intervals = [var["interval"] for var in task_vars.values() if var["dept"] == "Traction"]
    sig_intervals = [var["interval"] for var in task_vars.values() if var["dept"] in ("S&T", "Signalling")]

    if eng_intervals: model.AddNoOverlap(eng_intervals)
    if trac_intervals: model.AddNoOverlap(trac_intervals)
    if sig_intervals: model.AddNoOverlap(sig_intervals)

    # 4. Handle Task Dependencies
    for task in task_list:
        if "depends_on" in task and task["depends_on"] in task_vars:
            t_id = task["task_id"]
            dep_id = task["depends_on"]
            
            model.AddImplication(task_vars[t_id]["is_scheduled"], task_vars[dep_id]["is_scheduled"])
            model.Add(task_vars[t_id]["start"] >= task_vars[dep_id]["end"]).OnlyEnforceIf(task_vars[t_id]["is_scheduled"])

    model.Maximize(sum(var["priority"] * var["is_scheduled"] for var in task_vars.values()))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    response_payload = {
        "status": solver.StatusName(status),
        "total_priority": 0,
        "scheduled_tasks": []
    }

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        response_payload["total_priority"] = solver.ObjectiveValue()
        for task_id, var in task_vars.items():
            if solver.Value(var["is_scheduled"]):
                response_payload["scheduled_tasks"].append({
                    "task_id": task_id,
                    "department": var["dept"],
                    "start_time_iso": epoch_to_iso(solver.Value(var['start'])),
                    "end_time_iso": epoch_to_iso(solver.Value(var['end']))
                })
                
    return response_payload

if __name__ == "__main__":
    # --- Integration Test with Team A Data ---
    
    # Dummy train array mimicking image_ba2667.png
    train_data = [
        {"train_id": "123", "section_id": "BWN_to_BHP", "corridor_entry_time": "2026-09-01T10:00:00Z", "corridor_exit_time": "2026-09-01T10:05:00Z"},
        {"train_id": "124", "section_id": "BWN_to_BHP", "corridor_entry_time": "2026-09-01T14:30:00Z", "corridor_exit_time": "2026-09-01T14:35:00Z"}
    ]
    
    # Dummy task array mimicking image_ba266a.png
    task_data = [
        {"task_id": "TDMS-1001", "department": "Traction", "tier": "Tier 3", "section_id": "BWN_to_BHP", "work_duration_mins": 120},
        {"task_id": "TMS-1002", "department": "Engineering", "tier": "Tier 2", "section_id": "BWN_to_BHP", "work_duration_mins": 45}
    ]
    
    # Extract the block automatically instead of hardcoding it
    best_start, best_end = find_largest_corridor(train_data, "BWN_to_BHP")
    
    if best_start and best_end:
        result = generate_schedule(task_data, best_start, best_end)
        print(json.dumps(result, indent=2))
    else:
        print("No valid train gap found for this section.")