from ortools.sat.python import cp_model
from datetime import datetime
import json
import collections

def iso_to_epoch(iso_str):
    clean_str = iso_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_str)
    return int(dt.timestamp())

def epoch_to_iso(epoch_int):
    dt = datetime.utcfromtimestamp(epoch_int)
    return dt.isoformat() + "Z"

def find_corridors_for_all_sections(train_schedule):
    """Extracts ALL valid train-free gaps per section."""
    sections = set(t["section_id"] for t in train_schedule)
    corridors = collections.defaultdict(list)
    
    for section_id in sections:
        section_trains = [t for t in train_schedule if t["section_id"] == section_id]
        section_trains.sort(key=lambda x: iso_to_epoch(x["corridor_entry_time"]))
        
        for i in range(len(section_trains) - 1):
            current_exit = iso_to_epoch(section_trains[i]["corridor_exit_time"])
            next_entry = iso_to_epoch(section_trains[i+1]["corridor_entry_time"])
            
            gap = next_entry - current_exit
            # Only record gaps longer than the 15-minute safety buffer (900 seconds)
            if gap > 900:
                corridors[section_id].append((
                    section_trains[i]["corridor_exit_time"], 
                    section_trains[i+1]["corridor_entry_time"]
                ))
                
    return dict(corridors)

def generate_schedule(task_list, section_corridors):
    model = cp_model.CpModel()
    task_vars = {}
    
    # 3D Matrix to group intervals by Section, Corridor Index, and Department
    shadow_block_matrix = collections.defaultdict(list)

    for task in task_list:
        section_id = task["section_id"]
        if section_id not in section_corridors or not section_corridors[section_id]:
            continue
            
        task_id = task["task_id"]
        duration_sec = task["work_duration_mins"] * 60 
        dept = task["department"]
        priority = 100 if task.get("tier") == "Tier 1" else (70 if task.get("tier") == "Tier 2" else 40)
        
        # Calculate absolute time bounds across all corridors for this section
        all_starts = [iso_to_epoch(c[0]) for c in section_corridors[section_id]]
        all_ends = [iso_to_epoch(c[1]) - 900 for c in section_corridors[section_id]]
        overall_min, overall_max = min(all_starts), max(all_ends)
        
        # Global variables for the task
        task_is_scheduled = model.NewBoolVar(f'{task_id}_is_scheduled')
        task_start = model.NewIntVar(overall_min, overall_max, f'{task_id}_start')
        task_end = model.NewIntVar(overall_min, overall_max, f'{task_id}_end')
        
        corridor_presences = []
        
        # Create an optional interval for EVERY available time corridor
        for c_idx, (c_start_iso, c_end_iso) in enumerate(section_corridors[section_id]):
            c_start = iso_to_epoch(c_start_iso)
            safe_c_end = iso_to_epoch(c_end_iso) - 900
            
            # Skip if the task physically cannot fit in this specific gap
            if safe_c_end - c_start < duration_sec:
                continue
                
            presence_in_c = model.NewBoolVar(f'{task_id}_in_corridor_{c_idx}')
            corridor_presences.append(presence_in_c)
            
            local_start = model.NewIntVar(c_start, safe_c_end, f'{task_id}_c{c_idx}_start')
            local_end = model.NewIntVar(c_start, safe_c_end, f'{task_id}_c{c_idx}_end')
            local_interval = model.NewOptionalIntervalVar(local_start, duration_sec, local_end, presence_in_c, f'{task_id}_c{c_idx}_interval')
            
            # Link local gap variables to global task variables
            model.Add(task_start == local_start).OnlyEnforceIf(presence_in_c)
            model.Add(task_end == local_end).OnlyEnforceIf(presence_in_c)
            
            # Map this interval for Shadow Blocking
            if dept in ("Engineering", "Traction", "S&T", "Signalling"):
                shadow_block_matrix[(section_id, c_idx, dept)].append(local_interval)
                
        # A task can only be scheduled in AT MOST ONE corridor
        model.Add(sum(corridor_presences) == task_is_scheduled)
        model.Add(sum(corridor_presences) <= 1)
        
        task_vars[task_id] = {
            "start": task_start, "end": task_end,
            "is_scheduled": task_is_scheduled, "priority": priority,
            "dept": dept, "section_id": section_id
        }

    # Apply Shadow Blocking to isolated gaps
    for key, intervals in shadow_block_matrix.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    # Handle Global Task Dependencies
    for task in task_list:
        if "depends_on" in task and task["depends_on"] in task_vars and task["task_id"] in task_vars:
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

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        response_payload["total_priority"] = solver.ObjectiveValue()
        for task_id, var in task_vars.items():
            if solver.Value(var["is_scheduled"]):
                response_payload["scheduled_tasks"].append({
                    "task_id": task_id,
                    "section_id": var["section_id"],
                    "department": var["dept"],
                    "start_time_iso": epoch_to_iso(solver.Value(var['start'])),
                    "end_time_iso": epoch_to_iso(solver.Value(var['end']))
                })
                
    return response_payload

if __name__ == "__main__":
    train_data = [
        # BWN_to_BHP now has TWO distinct gaps: a 4.5hr gap in the morning, and a 2.5hr gap in the evening
        {"train_id": "123", "section_id": "BWN_to_BHP", "corridor_entry_time": "2026-09-01T10:00:00Z", "corridor_exit_time": "2026-09-01T10:05:00Z"},
        {"train_id": "124", "section_id": "BWN_to_BHP", "corridor_entry_time": "2026-09-01T14:30:00Z", "corridor_exit_time": "2026-09-01T14:35:00Z"},
        {"train_id": "125", "section_id": "BWN_to_BHP", "corridor_entry_time": "2026-09-01T17:00:00Z", "corridor_exit_time": "2026-09-01T17:05:00Z"}
    ]
    
    task_data = [
        {"task_id": "ENG-1", "department": "Engineering", "tier": "Tier 1", "section_id": "BWN_to_BHP", "work_duration_mins": 180},
        {"task_id": "ENG-2", "department": "Engineering", "tier": "Tier 2", "section_id": "BWN_to_BHP", "work_duration_mins": 120},
        {"task_id": "TRAC-1", "department": "Traction", "tier": "Tier 3", "section_id": "BWN_to_BHP", "work_duration_mins": 60, "depends_on": "ENG-1"}
    ]
    
    all_corridors = find_corridors_for_all_sections(train_data)
    result = generate_schedule(task_data, all_corridors)
    print(json.dumps(result, indent=2))