from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import Dict, Optional, List

class ArchitectureType(str, Enum):
    MONOLITH = "monolith"
    MICROSERVICES = "microservices"
    SERVERLESS = "serverless"
    HYBRID = "hybrid"

class CloudProvider(str, Enum):
    """Supported cloud providers (17 total)"""
    # Major Global
    AWS = "AWS"
    AZURE = "Azure"
    GCP = "GCP"
    ORACLE = "Oracle Cloud"
    IBM = "IBM Cloud"
    # Developer-Focused
    DIGITALOCEAN = "DigitalOcean"
    LINODE = "Linode"
    VULTR = "Vultr"
    HETZNER = "Hetzner"
    # Indian Providers
    TATA_IZO = "Tata IZO"
    CTRLS = "CtrlS"
    NETMAGIC = "Netmagic"
    YOTTA = "Yotta"
    # Regional/Specialized
    ALIBABA = "Alibaba Cloud"
    OVH = "OVHcloud"
    SCALEWAY = "Scaleway"
    VERCEL = "Vercel"

class DatabaseConfig(BaseModel):
    type: str = Field(default="rds", description="Database type: rds, dynamodb, firestore")
    read_replicas: int = Field(default=0, ge=0, le=10, description="Number of read replicas")
    backup_enabled: bool = Field(default=False, description="Enable automated backups")
    multi_az: bool = Field(default=False, description="Enable Multi-AZ deployment")
    cache_type: Optional[str] = Field(default=None, description="Cache type: redis, memcached, none")
    cache_size_gb: float = Field(default=0, ge=0, description="Cache memory size in GB")

class CDNConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable CDN")
    provider: str = Field(default="cloudfront", description="CDN provider: cloudfront, cloudflare, akamai")
    data_transfer_gb: float = Field(default=0, ge=0, description="Monthly data transfer in GB")
    edge_functions: bool = Field(default=False, description="Enable edge functions")
    video_streaming: bool = Field(default=False, description="Enable video streaming optimization")

class MessageQueueConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable message queuing")
    type: str = Field(default="sqs", description="Queue type: sqs, rabbitmq, kafka, kinesis")
    messages_per_day: int = Field(default=0, ge=0, description="Messages per day")
    retention_days: int = Field(default=7, ge=1, le=365, description="Message retention period")
    dlq_enabled: bool = Field(default=False, description="Enable Dead Letter Queue")

class SecurityConfig(BaseModel):
    waf_enabled: bool = Field(default=False, description="Enable WAF")
    vpn_enabled: bool = Field(default=False, description="Enable VPN")
    ddos_protection: bool = Field(default=False, description="Enable DDoS protection")
    ssl_certificates: int = Field(default=0, ge=0, description="Number of SSL certificates")
    compliance: List[str] = Field(default=[], description="Compliance standards: soc2, iso27001, hipaa, pci_dss")
    secrets_manager: bool = Field(default=False, description="Enable secrets management")

class MonitoringConfig(BaseModel):
    provider: str = Field(default="cloudwatch", description="Monitoring provider: cloudwatch, datadog, newrelic")
    log_retention_days: int = Field(default=7, ge=1, le=3650, description="Log retention period")
    apm_enabled: bool = Field(default=False, description="Enable APM")
    distributed_tracing: bool = Field(default=False, description="Enable distributed tracing")
    alert_channels: int = Field(default=0, ge=0, description="Number of alert channels")

class CICDConfig(BaseModel):
    provider: str = Field(default="github_actions", description="CI/CD provider: github_actions, gitlab_ci, jenkins")
    builds_per_month: int = Field(default=100, ge=0, description="Number of builds per month")
    container_registry: bool = Field(default=False, description="Use container registry")
    security_scanning: bool = Field(default=False, description="Enable security scanning")
    artifact_storage_gb: float = Field(default=0, ge=0, description="Artifact storage in GB")

class MultiRegionConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable multi-region")
    regions: int = Field(default=1, ge=1, le=20, description="Number of regions")
    replication_type: str = Field(default="active_passive", description="Replication: active_active, active_passive")
    cross_region_transfer_gb: float = Field(default=0, ge=0, description="Cross-region transfer in GB")
    rto_minutes: int = Field(default=60, ge=0, description="Recovery Time Objective")
    rpo_minutes: int = Field(default=60, ge=0, description="Recovery Point Objective")

class TrafficInput(BaseModel):
    daily_active_users: int = Field(..., gt=0, description="Expected Daily Active Users")
    api_requests_per_user: int = Field(default=50, description="API requests per user per day")
    storage_per_user_mb: float = Field(default=0.1, description="Storage per user in MB")
    peak_traffic_multiplier: float = Field(default=1.5, description="Peak traffic multiplier")
    growth_rate_yoy: float = Field(default=0.2, description="Year over year growth rate")
    revenue_per_user_monthly: float = Field(default=0, description="Revenue per user per month")
    funding_available: float = Field(default=0, description="Total funding available")
    
    # Advanced configuration
    database: DatabaseConfig = Field(default_factory=DatabaseConfig, description="Database configuration")
    cdn: CDNConfig = Field(default_factory=CDNConfig, description="CDN configuration")
    messaging: MessageQueueConfig = Field(default_factory=MessageQueueConfig, description="Message queue configuration")
    security: SecurityConfig = Field(default_factory=SecurityConfig, description="Security configuration")
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig, description="Monitoring configuration")
    cicd: CICDConfig = Field(default_factory=CICDConfig, description="CI/CD configuration")
    multi_region: MultiRegionConfig = Field(default_factory=MultiRegionConfig, description="Multi-region configuration")
    
    @field_validator('daily_active_users')
    @classmethod
    def validate_dau(cls, v):
        """Validate daily active users - cap at 1 billion to prevent overflow"""
        if v > 1_000_000_000:
            raise ValueError("Daily Active Users cannot exceed 1 billion. If you have more users, contact enterprise support.")
        if v < 1:
            raise ValueError("Daily Active Users must be at least 1")
        return v
    
    @field_validator('api_requests_per_user')
    @classmethod
    def validate_requests(cls, v):
        """Validate API requests per user - must be reasonable"""
        if v < 0:
            raise ValueError("API requests per user cannot be negative")
        if v > 1_000_000:
            raise ValueError("API requests per user cannot exceed 1,000,000. Please verify your input.")
        return max(0, v)
    
    @field_validator('storage_per_user_mb')
    @classmethod
    def validate_storage(cls, v):
        """Validate storage per user - must be non-negative"""
        if v < 0:
            raise ValueError("Storage per user cannot be negative")
        if v > 1_000_000:  # 1TB per user max
            raise ValueError("Storage per user cannot exceed 1,000,000 MB (1TB)")
        return max(0.0, v)
    
    @field_validator('peak_traffic_multiplier')
    @classmethod
    def validate_multiplier(cls, v):
        """Validate peak traffic multiplier - should be between 1.0 and 10.0"""
        if v < 1.0:
            raise ValueError("Peak traffic multiplier must be at least 1.0")
        if v > 10.0:
            raise ValueError("Peak traffic multiplier cannot exceed 10.0")
        return v
    
    @field_validator('growth_rate_yoy')
    @classmethod
    def validate_growth(cls, v):
        """Validate YoY growth rate - must be between -100% and 1000%"""
        if v < -1.0:
            raise ValueError("Growth rate cannot be less than -100%")
        if v > 10.0:
            raise ValueError("Growth rate cannot exceed 1000% (10.0)")
        return v
    
    @field_validator('revenue_per_user_monthly')
    @classmethod
    def validate_revenue(cls, v):
        """Validate revenue per user - cannot be negative"""
        if v < 0:
            raise ValueError("Revenue per user cannot be negative")
        if v > 1_000_000:
            raise ValueError("Revenue per user cannot exceed $1,000,000")
        return max(0.0, v)
    
    @field_validator('funding_available')
    @classmethod
    def validate_funding(cls, v):
        """Validate funding - cannot be negative"""
        if v < 0:
            raise ValueError("Funding available cannot be negative")
        if v > 1_000_000_000:  # $1B cap
            raise ValueError("Funding cannot exceed $1,000,000,000")
        return max(0.0, v)

class CostComponent(BaseModel):
    compute: float
    database: float
    storage: float
    networking: float
    cdn: float = 0
    messaging: float = 0
    security: float = 0
    monitoring: float = 0
    cicd: float = 0
    multi_region: float = 0
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

class FilterConfig(BaseModel):
    """Saved filter configuration for URL sharing"""
    filter_id: Optional[str] = None
    name: str = "My Configuration"
    cloud_provider: str = "AWS"
    architecture: ArchitectureType = ArchitectureType.MONOLITH
    traffic_input: TrafficInput
    created_at: Optional[str] = None
    
class ContactSubmission(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    subject: str = Field(..., min_length=5, max_length=200)
    message: str = Field(..., min_length=10, max_length=2000)
    created_at: Optional[str] = None
