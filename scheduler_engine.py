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

def generate_schedule(task_list, section_corridors):
    model = cp_model.CpModel()
    task_vars = {}
    
    # 3D Matrix to group intervals by Section, Corridor Index, and Department
    shadow_block_matrix = collections.defaultdict(list)

    for task in task_list:
        # Updated to match exact frontend casing
        section_id = task.get("SectionID")
        
        # Skip this task if there is no train gap available on its specific track section
        if section_id not in section_corridors or not section_corridors[section_id]:
            continue
            
        task_id = task.get("task-id")
        duration_sec = task.get("work_duration_mins", 0) * 60 
        dept = task.get("department")
        
        # Capture the new pass-through variables for the frontend
        req_date = task.get("date")
        maint_freq = task.get("maintenance_frequency", "special")
        
        priority = task.get("priority_score", 0)
        if priority == 0:
            tier = task.get("tier", "Tier 3")
            priority = 100 if tier == "Tier 1" else (70 if tier == "Tier 2" else 40)
            
        deadline_iso = task.get("deadline_iso")
        deadline_epoch = iso_to_epoch(deadline_iso) if deadline_iso else None
        
        all_starts = [iso_to_epoch(c[0]) for c in section_corridors[section_id]]
        all_ends = [iso_to_epoch(c[1]) - 900 for c in section_corridors[section_id]]
        overall_min, overall_max = min(all_starts), max(all_ends)
        
        task_is_scheduled = model.NewBoolVar(f'{task_id}_is_scheduled')
        task_start = model.NewIntVar(overall_min, overall_max, f'{task_id}_start')
        task_end = model.NewIntVar(overall_min, overall_max, f'{task_id}_end')
        
        if deadline_epoch:
            model.Add(task_end <= deadline_epoch).OnlyEnforceIf(task_is_scheduled)
        
        corridor_presences = []
        
        for c_idx, (c_start_iso, c_end_iso) in enumerate(section_corridors[section_id]):
            c_start = iso_to_epoch(c_start_iso)
            safe_c_end = iso_to_epoch(c_end_iso) - 900
            
            if safe_c_end - c_start < duration_sec:
                continue
                
            presence_in_c = model.NewBoolVar(f'{task_id}_in_corridor_{c_idx}')
            corridor_presences.append(presence_in_c)
            
            local_start = model.NewIntVar(c_start, safe_c_end, f'{task_id}_c{c_idx}_start')
            local_end = model.NewIntVar(c_start, safe_c_end, f'{task_id}_c{c_idx}_end')
            local_interval = model.NewOptionalIntervalVar(local_start, duration_sec, local_end, presence_in_c, f'{task_id}_c{c_idx}_interval')
            
            model.Add(task_start == local_start).OnlyEnforceIf(presence_in_c)
            model.Add(task_end == local_end).OnlyEnforceIf(presence_in_c)
            
            if dept in ("Engineering", "Traction", "S&T", "Signalling"):
                shadow_block_matrix[(section_id, c_idx, dept)].append(local_interval)
                
        model.Add(sum(corridor_presences) == task_is_scheduled)
        model.Add(sum(corridor_presences) <= 1)
        
        # Store all required data for the final output
        task_vars[task_id] = {
            "start": task_start, "end": task_end,
            "is_scheduled": task_is_scheduled, "priority": priority,
            "dept": dept, "SectionID": section_id,
            "date": req_date, "maintenance_frequency": maint_freq
        }

    for key, intervals in shadow_block_matrix.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    # Updated dependency check for new task-id key
    for task in task_list:
        dep_id = task.get("depends_on")
        if dep_id and dep_id in task_vars and task.get("task-id") in task_vars:
            t_id = task["task-id"]
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
                # Construct the final array with passthrough variables
                response_payload["scheduled_tasks"].append({
                    "task-id": task_id,
                    "SectionID": var["SectionID"],
                    "department": var["dept"],
                    "date": var["date"],
                    "maintenance_frequency": var["maintenance_frequency"],
                    "start_time_iso": epoch_to_iso(solver.Value(var['start'])),
                    "end_time_iso": epoch_to_iso(solver.Value(var['end']))
                })
                
    return response_payload

if __name__ == "__main__":
    member_e_corridors = {
        "HWH_to_BWN": [
            ("2026-09-01T15:53:00Z", "2026-09-02T02:37:00Z")
        ]
    }
    
    # Test data strictly matching the new frontend schema
    member_c_tasks = [
        {
            "task-id": "ENG-1", 
            "department": "Engineering",
            "tier": "Tier 1",
            "SectionID": "HWH_to_BWN",
            "date": "2026-09-01",
            "maintenance_frequency": "special",
            "work_duration_mins": 180,
            "depends_on": None,
            "priority_score": 0
        },
        {
            "task-id": "ROUTINE-WEEKLY",
            "department": "Traction",
            "tier": "Tier 2",
            "SectionID": "HWH_to_BWN",
            "date": "2026-09-01",
            "maintenance_frequency": "weekly",
            "work_duration_mins": 120,
            "depends_on": None,
            "priority_score": 0,
            "deadline_iso": "2026-09-02T00:00:00Z" 
        }
    ]
    
    result = generate_schedule(member_c_tasks, member_e_corridors)
    print(json.dumps(result, indent=2))