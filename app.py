# File: app.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import json

# Import the optimization engine built by Member D
from scheduler_engine import generate_schedule

app = FastAPI(title="Railway Auto-Block Planner API")

# Configure CORS so Member F's frontend can communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, this would be restricted to the frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Data Models (Data Validation) ---
class TaskSchema(BaseModel):
    id: str
    dept: str
    duration_mins: int
    priority: int
    depends_on: Optional[str] = None

class ScheduleRequest(BaseModel):
    corridor_start_iso: str
    corridor_end_iso: str
    tasks: List[TaskSchema]

# --- API Endpoints ---

@app.get("/api/v1/health")
def health_check():
    """Verify the server is running."""
    return {"status": "Backend and Engine are online"}

@app.get("/api/v1/mock-data")
def get_mock_data():
    """
    Serve Member B's mock database to the frontend.
    Assumes Member B created a file named 'mock_database.json'.
    """
    try:
        with open("mock_database.json", "r") as file:
            data = json.load(file)
        return {"tasks": data}
    except FileNotFoundError:
        # Fallback dummy data if Member B's file isn't ready
        return {"tasks": [
            {"id": "T1", "dept": "TDMS", "duration_mins": 30, "priority": 100, "depends_on": None},
            {"id": "T2", "dept": "TMS", "duration_mins": 120, "priority": 90, "depends_on": "T1"},
            {"id": "T3", "dept": "SMMS", "duration_mins": 60, "priority": 50, "depends_on": None}
        ]}

@app.post("/api/v1/optimize-schedule")
def optimize(request: ScheduleRequest):
    """
    The core endpoint. Takes the raw tasks, feeds them to Member D's engine, 
    and returns the Gantt chart coordinates.
    """
    try:
        # Convert Pydantic models to standard dictionaries
        task_list = [task.model_dump() for task in request.tasks]
        
        # Trigger the CP-SAT solver
        result = generate_schedule(
            task_list=task_list,
            corridor_start_iso=request.corridor_start_iso,
            corridor_end_iso=request.corridor_end_iso
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Starts the server on http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)