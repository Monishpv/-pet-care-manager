import datetime
from typing import Dict, Any, List
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("pet-care-server")

# In-memory database with realistic pre-populated data
PET_DATABASE: Dict[str, Dict[str, Any]] = {
    "buddy": {
        "name": "Buddy",
        "type": "dog",
        "breed": "Golden Retriever",
        "weight_kg": 30.5,
        "birth_date": "2022-04-12",
        "vaccines": {
            "Rabies": "2025-05-10",
            "DHPP": "2025-06-01",
            "Bordetella": "2024-11-15"
        },
        "feedings": [
            {"food_type": "Kibble", "time": "08:00", "quantity_grams": 250.0},
            {"food_type": "Kibble", "time": "18:00", "quantity_grams": 250.0}
        ],
        "vet_visits": [
            {"date": "2025-06-01", "description": "Annual wellness checkup and DHPP booster."}
        ]
    },
    "luna": {
        "name": "Luna",
        "type": "cat",
        "breed": "Siamese",
        "weight_kg": 4.2,
        "birth_date": "2023-08-20",
        "vaccines": {
            "FVRCP": "2025-01-15",
            "Rabies": "2024-02-10"
        },
        "feedings": [
            {"food_type": "Wet Food", "time": "07:30", "quantity_grams": 85.0},
            {"food_type": "Dry Food", "time": "19:00", "quantity_grams": 50.0}
        ],
        "vet_visits": [
            {"date": "2025-01-15", "description": "FVRCP booster shot."}
        ]
    }
}

@mcp.tool()
def get_pet_profile(pet_name: str) -> Dict[str, Any]:
    """Retrieve profile details for a pet, including type, breed, weight, birth date, and vaccination history.

    Args:
        pet_name: The name of the pet (case-insensitive).
    """
    name_key = pet_name.strip().lower()
    if name_key not in PET_DATABASE:
        return {"status": "error", "message": f"Pet '{pet_name}' not found. Available pets are: {', '.join(p.capitalize() for p in PET_DATABASE.keys())}"}
    return {"status": "success", "pet_profile": PET_DATABASE[name_key]}

@mcp.tool()
def schedule_feeding(pet_name: str, food_type: str, time: str, quantity_grams: float) -> Dict[str, Any]:
    """Add a new scheduled feeding for a pet.

    Args:
        pet_name: The name of the pet (case-insensitive).
        food_type: Type of food (e.g. Kibble, Wet Food, Treats).
        time: Time of feeding in 24h format (e.g. 08:00, 18:30).
        quantity_grams: Amount of food in grams.
    """
    name_key = pet_name.strip().lower()
    if name_key not in PET_DATABASE:
        return {"status": "error", "message": f"Pet '{pet_name}' not found."}
    
    new_feeding = {
        "food_type": food_type,
        "time": time,
        "quantity_grams": float(quantity_grams)
    }
    PET_DATABASE[name_key]["feedings"].append(new_feeding)
    return {
        "status": "success",
        "message": f"Successfully scheduled {quantity_grams}g of {food_type} for {PET_DATABASE[name_key]['name']} at {time}.",
        "feedings": PET_DATABASE[name_key]["feedings"]
    }

@mcp.tool()
def check_vaccine_compliance(pet_name: str) -> Dict[str, Any]:
    """Check a pet's vaccination record and identify any expired or overdue vaccines (required yearly).

    Args:
        pet_name: The name of the pet (case-insensitive).
    """
    name_key = pet_name.strip().lower()
    if name_key not in PET_DATABASE:
        return {"status": "error", "message": f"Pet '{pet_name}' not found."}
    
    profile = PET_DATABASE[name_key]
    pet_type = profile["type"]
    vaccines = profile["vaccines"]
    
    # We assume current date is 2026-06-25 (based on current system date)
    current_date = datetime.date(2026, 6, 25)
    compliance_report = []
    non_compliant = False
    
    required_vaccines = []
    if pet_type == "dog":
        required_vaccines = ["Rabies", "DHPP", "Bordetella"]
    elif pet_type == "cat":
        required_vaccines = ["Rabies", "FVRCP"]
        
    for vaccine in required_vaccines:
        if vaccine not in vaccines:
            compliance_report.append(f"❌ {vaccine}: Missing entirely.")
            non_compliant = True
        else:
            last_date_str = vaccines[vaccine]
            last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d").date()
            days_since = (current_date - last_date).days
            if days_since > 365:
                compliance_report.append(f"❌ {vaccine}: Expired! Last given on {last_date_str} ({days_since} days ago). Booster required.")
                non_compliant = True
            else:
                compliance_report.append(f"✅ {vaccine}: Up-to-date. Last given on {last_date_str}.")
                
    return {
        "status": "success",
        "compliant": not non_compliant,
        "pet_name": profile["name"],
        "report": compliance_report
    }

@mcp.tool()
def log_vet_visit(pet_name: str, description: str, date: str) -> Dict[str, Any]:
    """Log a vet visit and clinical notes for a pet.

    Args:
        pet_name: The name of the pet (case-insensitive).
        description: Description of the visit (e.g. checkup, vaccines given, diagnostic findings).
        date: Date of the visit in YYYY-MM-DD format.
    """
    name_key = pet_name.strip().lower()
    if name_key not in PET_DATABASE:
        return {"status": "error", "message": f"Pet '{pet_name}' not found."}
    
    new_visit = {
        "date": date,
        "description": description
    }
    PET_DATABASE[name_key]["vet_visits"].append(new_visit)
    
    # Auto-update vaccine date if vaccine logging detected in description
    for vaccine in ["Rabies", "DHPP", "Bordetella", "FVRCP"]:
        if vaccine.lower() in description.lower():
            PET_DATABASE[name_key]["vaccines"][vaccine] = date
            
    return {
        "status": "success",
        "message": f"Successfully logged vet visit for {PET_DATABASE[name_key]['name']} on {date}.",
        "vet_visits": PET_DATABASE[name_key]["vet_visits"],
        "updated_vaccines": PET_DATABASE[name_key]["vaccines"]
    }

if __name__ == "__main__":
    mcp.run()
