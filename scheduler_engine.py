from ortools.sat.python import cp_model
from datetime import datetime
import json

def iso_to_epoch(iso_str):
    """Converts a timestamp like '2026-09-05T10:00:00' to integer seconds."""
    dt = datetime.fromisoformat(iso_str)
    return int(dt.timestamp())

def epoch_to_iso(epoch_int):
    """Converts integer seconds back into a readable timestamp."""
    return datetime.fromtimestamp(epoch_int).isoformat()

def generate_schedule(task_list, corridor_start_iso, corridor_end_iso):
    model = cp_model.CpModel()
    task_vars = {}
    
    # 1. Convert corridor times to UNIX epoch (seconds)
    corridor_start = iso_to_epoch(corridor_start_iso)
    corridor_end = iso_to_epoch(corridor_end_iso)
    
    # Railway Rule: All work must stop 15 minutes (900 seconds) before trains resume
    safe_corridor_end = corridor_end - 900 

    # 2. Initialize variables for each task
    for task in task_list:
        task_id = task["id"]
        # Convert minutes to seconds for the solver
        duration_sec = task["duration_mins"] * 60 
        
        is_scheduled = model.NewBoolVar(f'{task_id}_is_present')
        start = model.NewIntVar(corridor_start, safe_corridor_end, f'{task_id}_start')
        end = model.NewIntVar(corridor_start, safe_corridor_end, f'{task_id}_end')
        
        interval = model.NewOptionalIntervalVar(
            start, duration_sec, end, is_scheduled, f'{task_id}_interval'
        )
        
        task_vars[task_id] = {
            "start": start, "end": end, "interval": interval, 
            "is_scheduled": is_scheduled, "priority": task["priority"],
            "dept": task["dept"]
        }

    # 3. Handle Shadow Block Logic (No overlaps within same department)
    tms_intervals = [var["interval"] for var in task_vars.values() if var["dept"] == "TMS"]
    smms_intervals = [var["interval"] for var in task_vars.values() if var["dept"] == "SMMS"]
    tdms_intervals = [var["interval"] for var in task_vars.values() if var["dept"] == "TDMS"]

    if tms_intervals: model.AddNoOverlap(tms_intervals)
    if smms_intervals: model.AddNoOverlap(smms_intervals)
    if tdms_intervals: model.AddNoOverlap(tdms_intervals)

    # 4. Handle Task Dependencies (Precedence constraints)
    for task in task_list:
        if "depends_on" in task and task["depends_on"] in task_vars:
            t_id = task["id"]
            dep_id = task["depends_on"]
            
            # Rule A: If Task 2 is scheduled, Task 1 MUST also be scheduled
            model.AddImplication(task_vars[t_id]["is_scheduled"], task_vars[dep_id]["is_scheduled"])
            
            # Rule B: If Task 2 is scheduled, its start time must be >= Task 1's end time
            model.Add(task_vars[t_id]["start"] >= task_vars[dep_id]["end"]).OnlyEnforceIf(task_vars[t_id]["is_scheduled"])

    # 5. Maximize total priority
    model.Maximize(sum(var["priority"] * var["is_scheduled"] for var in task_vars.values()))

    # 6. Solve the model
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    # 7. Build the JSON response for Member E (Backend)
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
                    "dept": var["dept"],
                    "start_time_iso": epoch_to_iso(solver.Value(var['start'])),
                    "end_time_iso": epoch_to_iso(solver.Value(var['end']))
                })
                
    return response_payload

# --- Test the API Function ---
if __name__ == "__main__":
    # Mock payload simulating real database JSON
    dummy_tasks = [
        {"id": "T1", "dept": "TDMS", "duration_mins": 30, "priority": 100}, # Power cut
        {"id": "T2", "dept": "TMS", "duration_mins": 120, "priority": 90, "depends_on": "T1"}, # Track repair (requires power cut first)
        {"id": "T3", "dept": "SMMS", "duration_mins": 60, "priority": 50}, 
        {"id": "T4", "dept": "TMS", "duration_mins": 180, "priority": 85} 
    ]
    
    corridor_start = "2026-09-05T10:00:00"
    corridor_end = "2026-09-05T14:00:00"
    
    result = generate_schedule(dummy_tasks, corridor_start, corridor_end)
    print(json.dumps(result, indent=2))