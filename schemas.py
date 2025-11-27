from enum import Enum
from pydantic import BaseModel, Field
from typing import Dict, Optional, List

class ArchitectureType(str, Enum):
    MONOLITH = "monolith"
    MICROSERVICES = "microservices"
    SERVERLESS = "serverless"
    HYBRID = "hybrid"

class TrafficInput(BaseModel):
    daily_active_users: int = Field(..., gt=0, description="Expected Daily Active Users")
    api_requests_per_user: int = Field(default=50, description="API requests per user per day")
    storage_per_user_mb: float = Field(default=0.1, description="Storage per user in MB")
    peak_traffic_multiplier: float = Field(default=1.5, description="Peak traffic multiplier")
    growth_rate_yoy: float = Field(default=0.2, description="Year over year growth rate")
    revenue_per_user_monthly: float = Field(default=0, description="Revenue per user per month")
    funding_available: float = Field(default=0, description="Total funding available")

class CostComponent(BaseModel):
    compute: float
    database: float
    storage: float
    networking: float
    total: float

class EstimationResult(BaseModel):
    architecture: ArchitectureType
    traffic_input: TrafficInput
    monthly_cost: CostComponent
    yearly_cost: float
    three_year_projection: Dict[str, float]  # "Year 1": cost, ...
    infrastructure_requirements: Dict[str, str]  # "Compute": "2x t3.medium", ...
    multi_cloud_costs: Dict[str, float] = {}  # "AWS": 100, "Azure": 105, ...
    scaling_scenarios: Dict[str, float] = {}  # "10k Users": 500, "100k Users": 4000, ...
    optimization_suggestions: List[Dict[str, str]] = []  # [{"title": "Reserved Instances", "saving": "$200", "description": "..."}]
    business_metrics: Dict[str, str] = {}  # "Cost per User": "$0.05", "Runway": "12 months"
