from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from datetime import datetime, timedelta

# Import Member D's upgraded mathematical engine functions
from scheduler_engine import find_corridors_for_all_sections, generate_schedule

app = FastAPI(title="Railway Central Routing API")

# Configure CORS so Member F's frontend can communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Establish Day 1.0 of the simulation schedule 
SIMULATION_BASE_DATE = datetime(2026, 9, 1)

def convert_day_time_to_iso(day_float: float, time_str: str) -> str:
    """Converts Member B's day/time format into standard ISO 8601 strings."""
    day_offset = int(day_float) - 1
    t_obj = datetime.strptime(time_str, "%H:%M:%S").time()
    
    target_date = SIMULATION_BASE_DATE + timedelta(days=day_offset)
    target_datetime = target_date.replace(hour=t_obj.hour, minute=t_obj.minute, second=t_obj.second)
    
    return target_datetime.isoformat() + "Z"

# --- PHASE 1: Data Ingestion (Pydantic Validation Models) ---
# These exactly match the JSON format of Member B's new massive dataset

class TrainMovementRaw(BaseModel):
    train_no: str
    direction: str
    section_id: str
    start_day: float
    entry_time: str
    end_day: float
    exit_time: str

class MaintenanceTask(BaseModel):
    task_id: str
    department: str
    tier: str = "Tier 3"
    section_id: str
    work_duration_mins: int
    depends_on: Optional[str] = None
    priority_score: Optional[int] = 0 

class OptimizationRequest(BaseModel):
    train_schedule: List[TrainMovementRaw]
    pending_tasks: List[MaintenanceTask]


# --- PHASE 3: AI Routing (Member C Integration Placeholder) ---

def invoke_ml_scoring(tasks: List[dict]) -> List[dict]:
    """
    Placeholder for Member C's Machine Learning model.
    Until they provide their predict_risk.py script, this function assigns static baseline scores.
    """
    for task in tasks:
        if task.get("priority_score") == 0 or not task.get("priority_score"):
            tier = task.get("tier", "Tier 3")
            task["priority_score"] = 100 if tier == "Tier 1" else (70 if tier == "Tier 2" else 40)
    return tasks


# --- THE MAIN PIPELINE ENDPOINT ---

@app.get("/api/v1/health")
def health_check():
    """Verify the server is running."""
    return {"status": "Central Routing API is online"}

@app.post("/api/v1/optimize-schedule")
def optimize_corridors(request: OptimizationRequest):
    """
    The central loop connecting the DB, ML, Engine, and Frontend.
    """
    try:
        # PHASE 1: Data Ingestion & Translation Layer
        raw_tasks = [t.model_dump() for t in request.pending_tasks]
        
        # Translate Member B's custom format into Member D's required ISO format
        mapped_train_data = []
        for raw_train in request.train_schedule:
            mapped_train_data.append({
                "train_id": raw_train.train_no,
                "section_id": raw_train.section_id,
                "corridor_entry_time": convert_day_time_to_iso(raw_train.start_day, raw_train.entry_time),
                "corridor_exit_time": convert_day_time_to_iso(raw_train.end_day, raw_train.exit_time)
            })

        # PHASE 2: Gap Extraction 
        # Member D's engine now receives the exact data structure it was originally built for
        section_corridors = find_corridors_for_all_sections(mapped_train_data)

        # PHASE 3: AI Routing
        scored_tasks = invoke_ml_scoring(raw_tasks)

        # Prepare keys for Member D's engine
        for t in scored_tasks:
            t["priority"] = t["priority_score"]

        # PHASE 4: The Engine Handoff
        optimization_result = generate_schedule(scored_tasks, section_corridors)
        scheduled_tasks = optimization_result.get("scheduled_tasks", [])

        # PHASE 5: Backlog & Aging Management
        scheduled_task_ids = {t["task_id"] for t in scheduled_tasks}
        backlog = []
        
        for task in scored_tasks:
            if task["task_id"] not in scheduled_task_ids:
                # The solver dropped this task. Apply the Aging function (+10 priority).
                task["priority_score"] += 10
                task.pop("priority", None) # Clean up the dictionary
                backlog.append(task)

        # PHASE 6: Frontend Delivery
        return {
            "status": optimization_result.get("status"),
            "total_priority_scheduled": optimization_result.get("total_priority"),
            "scheduled_timeline": scheduled_tasks,
            "updated_backlog": backlog
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # Starts the server on http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)