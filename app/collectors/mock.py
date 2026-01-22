"""
AAM Mock Collector

Generates sample observations from JSON for testing.
Used to validate the inference and pipe registry flow before adding real collectors.
"""
from datetime import datetime
from typing import Optional
import uuid

from ..db import create_observation, update_collector_last_run, get_candidate

MOCK_COLLECTOR_ID = "mock-collector-001"


def run_mock_collector(candidate_id: Optional[str] = None) -> list[dict]:
    """
    Run the mock collector to generate sample observations.
    
    If candidate_id is provided, generates observations based on that candidate.
    Otherwise, generates generic sample observations.
    
    Returns list of created observations.
    """
    observations = []
    
    if candidate_id:
        candidate = get_candidate(candidate_id)
        if candidate:
            observations = _generate_observations_from_candidate(candidate)
    else:
        observations = _generate_sample_observations()
    
    # Persist observations
    created = []
    for obs in observations:
        obs_id = create_observation(obs)
        obs["observation_id"] = obs_id
        created.append(obs)
    
    # Update collector last run
    update_collector_last_run(MOCK_COLLECTOR_ID)
    
    return created


def _generate_observations_from_candidate(candidate: dict) -> list[dict]:
    """Generate observations based on candidate data"""
    observations = []
    vendor = candidate["vendor_name"]
    category = candidate["category"]
    
    # Generate observations based on known endpoints
    endpoints = candidate.get("known_endpoints", [])
    if not endpoints:
        endpoints = [f"/api/{vendor.lower()}/v1/data"]
    
    for endpoint in endpoints:
        obs = {
            "collector_id": MOCK_COLLECTOR_ID,
            "candidate_id": candidate["candidate_id"],
            "observed_at": datetime.utcnow().isoformat(),
            "source_system": vendor,
            "endpoint_info": {
                "url": endpoint,
                "method": "GET",
                "discovered_via": "mock_collector"
            },
            "entity_hints": _infer_entity_hints(endpoint, category),
            "schema_sample": _generate_schema_sample(endpoint, category),
            "metadata": {
                "category": category,
                "vendor": vendor,
                "priority_score": candidate.get("priority_score")
            }
        }
        observations.append(obs)
    
    return observations


def _generate_sample_observations() -> list[dict]:
    """Generate generic sample observations for testing"""
    now = datetime.utcnow().isoformat()
    
    return [
        {
            "collector_id": MOCK_COLLECTOR_ID,
            "candidate_id": None,
            "observed_at": now,
            "source_system": "Salesforce",
            "endpoint_info": {
                "url": "/services/data/v58.0/sobjects/Account",
                "method": "GET",
                "discovered_via": "mock_collector"
            },
            "entity_hints": ["Account", "Customer", "Organization"],
            "schema_sample": {
                "Id": "string",
                "Name": "string",
                "Type": "string",
                "Industry": "string",
                "BillingAddress": "object",
                "CreatedDate": "datetime",
                "LastModifiedDate": "datetime"
            },
            "metadata": {
                "category": "CRM",
                "vendor": "Salesforce"
            }
        },
        {
            "collector_id": MOCK_COLLECTOR_ID,
            "candidate_id": None,
            "observed_at": now,
            "source_system": "Salesforce",
            "endpoint_info": {
                "url": "/services/data/v58.0/sobjects/Contact",
                "method": "GET",
                "discovered_via": "mock_collector"
            },
            "entity_hints": ["Contact", "Person", "Customer"],
            "schema_sample": {
                "Id": "string",
                "FirstName": "string",
                "LastName": "string",
                "Email": "string",
                "AccountId": "string",
                "CreatedDate": "datetime"
            },
            "metadata": {
                "category": "CRM",
                "vendor": "Salesforce"
            }
        },
        {
            "collector_id": MOCK_COLLECTOR_ID,
            "candidate_id": None,
            "observed_at": now,
            "source_system": "Workato",
            "endpoint_info": {
                "url": "/api/recipes/123/connections",
                "method": "GET",
                "discovered_via": "mock_collector"
            },
            "entity_hints": ["Recipe", "Integration", "Connection"],
            "schema_sample": {
                "id": "integer",
                "name": "string",
                "source_app": "string",
                "target_app": "string",
                "status": "string",
                "last_run": "datetime"
            },
            "metadata": {
                "category": "iPaaS",
                "vendor": "Workato"
            }
        }
    ]


def _infer_entity_hints(endpoint: str, category: str) -> list[str]:
    """Infer entity hints from endpoint and category"""
    hints = []
    
    # Extract entity from URL path
    parts = endpoint.lower().split("/")
    for part in parts:
        if part and part not in ["api", "v1", "v2", "data", "services", "sobjects"]:
            if not part.startswith("{") and not part.isdigit():
                hints.append(part.title())
    
    # Add category-based hints
    category_hints = {
        "CRM": ["Customer", "Account", "Contact", "Lead"],
        "ERP": ["Order", "Invoice", "Product", "Inventory"],
        "HRIS": ["Employee", "Department", "Payroll"],
        "iPaaS": ["Integration", "Recipe", "Connection"]
    }
    
    if category in category_hints:
        hints.extend([h for h in category_hints[category][:2] if h not in hints])
    
    return hints[:5]  # Limit to 5 hints


def _generate_schema_sample(endpoint: str, category: str) -> dict:
    """Generate sample schema based on endpoint and category"""
    base_schema = {
        "id": "string",
        "name": "string",
        "created_at": "datetime",
        "updated_at": "datetime"
    }
    
    # Add category-specific fields
    if category == "CRM":
        base_schema.update({
            "email": "string",
            "phone": "string",
            "status": "string"
        })
    elif category == "ERP":
        base_schema.update({
            "quantity": "integer",
            "price": "decimal",
            "currency": "string"
        })
    elif category == "HRIS":
        base_schema.update({
            "employee_id": "string",
            "department": "string",
            "hire_date": "date"
        })
    
    return base_schema
