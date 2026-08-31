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
        section_id = task.get("section_id")
        
        # Skip this task if there is no train gap available on its specific track section
        if section_id not in section_corridors or not section_corridors[section_id]:
            continue
            
        task_id = task.get("task_id")
        duration_sec = task.get("work_duration_mins", 0) * 60 
        dept = task.get("department")
        
        # Integrate Member C's ML Priority, with a fallback to string tiers if ML outputs 0
        priority = task.get("priority_score", 0)
        if priority == 0:
            tier = task.get("tier", "Tier 3")
            priority = 100 if tier == "Tier 1" else (70 if tier == "Tier 2" else 40)
        
        all_starts = [iso_to_epoch(c[0]) for c in section_corridors[section_id]]
        all_ends = [iso_to_epoch(c[1]) - 900 for c in section_corridors[section_id]]
        overall_min, overall_max = min(all_starts), max(all_ends)
        
        task_is_scheduled = model.NewBoolVar(f'{task_id}_is_scheduled')
        task_start = model.NewIntVar(overall_min, overall_max, f'{task_id}_start')
        task_end = model.NewIntVar(overall_min, overall_max, f'{task_id}_end')
        
        corridor_presences = []
        
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
            
            model.Add(task_start == local_start).OnlyEnforceIf(presence_in_c)
            model.Add(task_end == local_end).OnlyEnforceIf(presence_in_c)
            
            # Map this interval for Shadow Blocking
            if dept in ("Engineering", "Traction", "S&T", "Signalling"):
                shadow_block_matrix[(section_id, c_idx, dept)].append(local_interval)
                
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

    # Handle Global Task Dependencies (Safely ignores 'null' values from JSON)
    for task in task_list:
        dep_id = task.get("depends_on")
        if dep_id and dep_id in task_vars and task.get("task_id") in task_vars:
            t_id = task["task_id"]
            
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
    # Test Data identically matching Member E and Member C formats
    member_e_corridors = {
        "HWH_to_BWN": [
            ("2026-09-01T15:53:00Z", "2026-09-02T02:37:00Z")
        ],
        "KNE_to_NJP": [
            ("2026-09-01T02:26:00Z", "2026-09-02T01:00:00Z")
        ]
    }
    
    member_c_tasks = [
        {
            "task_id": "ENG-1",
            "department": "Engineering",
            "tier": "Tier 1",
            "section_id": "HWH_to_BWN",
            "work_duration_mins": 180,
            "depends_on": None,
            "priority_score": 0
        },
        {
            "task_id": "SIG-99",
            "department": "Signalling",
            "tier": "Tier 3",
            "section_id": "HWH_to_BWN",
            "work_duration_mins": 400,
            "depends_on": "ENG-1",
            "priority_score": 0
        }
    ]
    
    result = generate_schedule(member_c_tasks, member_e_corridors)
    print(json.dumps(result, indent=2))