from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import uvicorn
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
import uuid
import collections

# Import your mathematical engine
from scheduler_engine import generate_schedule

# --- MOCK DATABASE ---
DB_ACTIVE_QUEUE = []       
DB_BACKLOG = []            
DB_RECURRING_RULES = []    
DB_FINAL_SCHEDULE = []     
DB_TRAIN_SCHEDULE = []     

SIMULATION_BASE_DATE = datetime(2026, 9, 1)

def convert_day_time_to_iso(day_float: float, time_str: str) -> str:
    day_offset = int(day_float) - 1
    t_obj = datetime.strptime(time_str, "%H:%M:%S").time()
    target_date = SIMULATION_BASE_DATE + timedelta(days=day_offset)
    target_datetime = target_date.replace(hour=t_obj.hour, minute=t_obj.minute, second=t_obj.second)
    return target_datetime.isoformat() + "Z"

def iso_to_epoch(iso_str):
    clean_str = iso_str.replace("Z", "+00:00")
    return int(datetime.fromisoformat(clean_str).timestamp())

def find_corridors_for_all_sections(train_schedule):
    """Extracts empty track gaps to pass to Member D's engine."""
    sections = set(t["section_id"] for t in train_schedule)
    corridors = collections.defaultdict(list)
    
    for section_id in sections:
        section_trains = [t for t in train_schedule if t["section_id"] == section_id]
        section_trains.sort(key=lambda x: iso_to_epoch(x["corridor_entry_time"]))
        
        for i in range(len(section_trains) - 1):
            current_exit = iso_to_epoch(section_trains[i]["corridor_exit_time"])
            next_entry = iso_to_epoch(section_trains[i+1]["corridor_entry_time"])
            gap = next_entry - current_exit
            if gap > 900: # 15 min buffer
                corridors[section_id].append((
                    section_trains[i]["corridor_exit_time"], 
                    section_trains[i+1]["corridor_entry_time"]
                ))
    return dict(corridors)

# --- PYDANTIC VALIDATION MODELS (Updated for Member F's Schema) ---
class TrainMovementRaw(BaseModel):
    train_no: str
    direction: str
    SectionID: str = Field(..., alias="SectionID")
    start_day: float
    entry_time: str
    end_day: float
    exit_time: str

class MaintenanceTask(BaseModel):
    task_id: str = Field(..., alias="task-id")
    department: str # TMS, TDMS, SMMS
    SectionID: str = Field(..., alias="SectionID")
    date: str
    maintenance_frequency: str # "special", "weekly", "monthly"
    work_duration_mins: int

class SimulationPayload(BaseModel):
    train_schedule: List[TrainMovementRaw]
    pending_tasks: List[MaintenanceTask]

def invoke_ml_scoring(tasks: List[dict]) -> List[dict]:
    # Simulates Member C's logic - inflates score for delayed/routine tasks
    for task in tasks:
        freq = task.get("maintenance_frequency", "special")
        if "priority_score" not in task:
            task["priority_score"] = 80 if freq == "special" else 50
    return tasks

# --- THE 12:30 AM BATCH PROCESSOR ---
def run_midnight_batch_job():
    global DB_ACTIVE_QUEUE, DB_BACKLOG, DB_FINAL_SCHEDULE, DB_RECURRING_RULES
    print(f"\n--- [12:30 AM BATCH JOB INITIATED at {datetime.now()}] ---")
    
    try:
        # STEP A: Generate Tickets from Recurring Rules (Weekly/Monthly)
        generated_routine_tasks = []
        current_epoch = int(datetime.now().timestamp())
        
        for rule in DB_RECURRING_RULES:
            anchor_epoch = iso_to_epoch(rule["date"])
            days_passed = (current_epoch - anchor_epoch) / 86400
            
            # If a weekly rule is 7+ days old, spawn a ticket
            if rule["maintenance_frequency"] == "weekly" and days_passed >= 7:
                new_task = rule.copy()
                new_task["task-id"] = f"{rule['task-id']}-AUTO"
                new_task["secret_id"] = str(uuid.uuid4())
                new_task["date"] = datetime.now().isoformat() + "Z"
                generated_routine_tasks.append(new_task)
                rule["date"] = new_task["date"] # Reset anchor
                print(f"-> Generated recurring ticket: {new_task['task-id']}")

        # STEP B: Merge ALL THREE Data Sources
        combined_tasks = DB_ACTIVE_QUEUE + DB_BACKLOG + generated_routine_tasks
        
        if not combined_tasks or not DB_TRAIN_SCHEDULE:
            print("⚠️ No tasks or train schedules found in the database to process.")
            return

        # STEP C: Map Train Schedule for Gap Extraction
        mapped_train_data = []
        for raw_train in DB_TRAIN_SCHEDULE:
            mapped_train_data.append({
                "train_id": raw_train["train_no"],
                "section_id": raw_train["SectionID"], # Mapping alias back to internal logic
                "corridor_entry_time": convert_day_time_to_iso(raw_train["start_day"], raw_train["entry_time"]),
                "corridor_exit_time": convert_day_time_to_iso(raw_train["end_day"], raw_train["exit_time"])
            })

        section_corridors = find_corridors_for_all_sections(mapped_train_data)
        
        # Standardize keys for Member D's Engine
        engine_ready_tasks = []
        for t in combined_tasks:
            engine_task = t.copy()
            engine_task["task_id"] = t["task-id"]
            engine_task["section_id"] = t["SectionID"]
            engine_ready_tasks.append(engine_task)

        scored_tasks = invoke_ml_scoring(engine_ready_tasks)
        
        # Run Mathematical Engine
        optimization_result = generate_schedule(scored_tasks, section_corridors)
        scheduled_winners = optimization_result.get("scheduled_tasks", [])
        winner_map = {w["task_id"]: w for w in scheduled_winners}

        # STEP D: The Output Wrapper (Frontend Handoff)
        final_frontend_payload = []
        new_backlog = []
        
        for original_task in combined_tasks:
            task_id = original_task["task-id"]
            if task_id in winner_map:
                # Task Approved: Attach time bounds
                original_task["status"] = "Approved"
                original_task["start_time_iso"] = winner_map[task_id]["start_time_iso"]
                original_task["end_time_iso"] = winner_map[task_id]["end_time_iso"]
                final_frontend_payload.append(original_task)
            else:
                # Task Rejected: Send to backlog, flag as not approved
                original_task["status"] = "Not Approved"
                final_frontend_payload.append(original_task)
                
                # Strip the status/time flags before putting back into DB backlog
                clean_backlog_task = original_task.copy()
                clean_backlog_task.pop("status", None)
                new_backlog.append(clean_backlog_task)

        DB_BACKLOG = new_backlog
        DB_FINAL_SCHEDULE = final_frontend_payload
        DB_ACTIVE_QUEUE = []  

        print(f"2. Optimization status: {optimization_result.get('status')}")
        print(f"3. Sent {len(final_frontend_payload)} tasks back to UI. {len(new_backlog)} went to DB backlog.")
        
    except Exception as e:
        print(f"❌ Batch job failed with error: {str(e)}")

    print("--- [BATCH JOB COMPLETED] ---\n")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_midnight_batch_job, 'cron', hour=0, minute=30)
    scheduler.start()
    print("✅ APScheduler active. Waiting for 12:30 AM batch run...")
    yield
    scheduler.shutdown()

app = FastAPI(title="Railway Central Routing API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- API ENDPOINTS ---
@app.post("/api/v1/submit-tasks")
def submit_tasks(payload: SimulationPayload):
    global DB_TRAIN_SCHEDULE
    
    # Dump using by_alias=True to preserve frontend's exact 'task-id' and 'SectionID' keys
    DB_TRAIN_SCHEDULE = [t.model_dump(by_alias=True) for t in payload.train_schedule]
    
    for task in payload.pending_tasks:
        task_dict = task.model_dump(by_alias=True)
        task_dict["secret_id"] = str(uuid.uuid4()) # Injects the secret backend ID
        DB_ACTIVE_QUEUE.append(task_dict)
        
    return {"status": "Success", "message": f"Stored {len(payload.pending_tasks)} ad-hoc tasks."}

@app.post("/api/v1/add-recurring-rule")
def add_recurring_rule(rule: MaintenanceTask):
    """Endpoint for Member F's 'Weekly/Monthly Plan' tabs."""
    rule_dict = rule.model_dump(by_alias=True)
    rule_dict["secret_id"] = str(uuid.uuid4())
    DB_RECURRING_RULES.append(rule_dict)
    return {"status": "Success", "message": f"Recurring rule {rule_dict['task-id']} saved."}

@app.post("/api/v1/trigger-batch-run")
def force_run():
    run_midnight_batch_job()
    return {
        "status": "Batch run executed!", 
        "frontend_payload": DB_FINAL_SCHEDULE
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
