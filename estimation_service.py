from schemas import (
    TrafficInput, ArchitectureType, EstimationResult, CostComponent,
    DatabaseConfig, CDNConfig, MessageQueueConfig, SecurityConfig,
    MonitoringConfig, CICDConfig, MultiRegionConfig
)
from pricing_service import PricingService

class EstimationService:
    
    @staticmethod
    def calculate_database_cost(traffic: TrafficInput, db_config: DatabaseConfig, base_db_cost: float) -> tuple[float, dict]:
        """Calculate database and cache costs"""
        cost = base_db_cost
        reqs = {}
        
        # Read replicas
        if db_config.read_replicas > 0:
            replica_cost = db_config.read_replicas * PricingService.get_price("database", "read_replica")
            cost += replica_cost
            reqs[f"Read Replicas"] = f"{db_config.read_replicas}x replicas"
        
        # Multi-AZ (adds ~100% cost for redundancy)
        if db_config.multi_az:
            cost *= 2.0
            reqs["Multi-AZ"] = "Enabled for HA"
        
        # Backups
        if db_config.backup_enabled:
            # Assume backups are ~20% of data size
            backup_gb = (traffic.daily_active_users * traffic.storage_per_user_mb) / 1024 * 0.2
            backup_cost = backup_gb * PricingService.get_price("database", "backup_gb")
            cost += backup_cost
            reqs["Backups"] = f"{backup_gb:.1f} GB retained"
        
        # Cache
        cache_cost = 0
        if db_config.cache_type and db_config.cache_size_gb > 0:
            if db_config.cache_size_gb <= 1:
                cache_cost = PricingService.get_price("cache", f"{db_config.cache_type}_t4g_micro")
            elif db_config.cache_size_gb <= 3:
                cache_cost = PricingService.get_price("cache", f"{db_config.cache_type}_t4g_small")
            else:
                cache_cost = PricingService.get_price("cache", f"{db_config.cache_type}_t4g_medium")
            
            cost += cache_cost
            reqs["Cache"] = f"{db_config.cache_type.title()} ({db_config.cache_size_gb}GB)"
        
        return cost, reqs
    
    @staticmethod
    def calculate_cdn_cost(cdn_config: CDNConfig) -> tuple[float, dict]:
        """Calculate CDN costs"""
        if not cdn_config.enabled:
            return 0.0, {}
        
        cost = 0.0
        reqs = {}
        
        # Data transfer
        provider_key = f"{cdn_config.provider}_gb"
        data_cost = cdn_config.data_transfer_gb * PricingService.get_price("cdn", provider_key)
        cost += data_cost
        reqs["CDN Transfer"] = f"{cdn_config.data_transfer_gb} GB/mo via {cdn_config.provider.title()}"
        
        # Edge functions
        if cdn_config.edge_functions:
            # Assume 10% of requests use edge functions
            edge_requests = cdn_config.data_transfer_gb * 100 / 1024  # Rough conversion
            edge_cost = (edge_requests / 1000000) * PricingService.get_price("cdn", f"{cdn_config.provider}_edge_function_1m")
            cost += edge_cost
            reqs["Edge Functions"] = "Enabled"
        
        # Video streaming
        if cdn_config.video_streaming:
            multiplier = PricingService.get_price("cdn", "video_streaming_multiplier")
            cost *= multiplier
            reqs["Video Streaming"] = "Optimized"
        
        return cost, reqs
    
    @staticmethod
    def calculate_messaging_cost(msg_config: MessageQueueConfig, traffic: TrafficInput) -> tuple[float, dict]:
        """Calculate message queue costs"""
        if not msg_config.enabled:
            return 0.0, {}
        
        cost = 0.0
        reqs = {}
        
        if msg_config.type == "sqs":
            # SQS pricing
            monthly_messages = msg_config.messages_per_day * 30
            cost = (monthly_messages / 1000000) * PricingService.get_price("messaging", "sqs_1m_requests")
            reqs["Queue"] = f"SQS - {monthly_messages:,.0f} msgs/mo"
            
        elif msg_config.type == "kafka":
            # Kafka broker cost
            brokers = max(3, (msg_config.messages_per_day // 1000000) + 1)  # At least 3 for HA
            cost = brokers * PricingService.get_price("messaging", "kafka_broker")
            reqs["Queue"] = f"Kafka - {brokers} brokers"
            
        elif msg_config.type == "rabbitmq":
            cost = PricingService.get_price("messaging", "rabbitmq_m5_large")
            reqs["Queue"] = "RabbitMQ m5.large"
            
        elif msg_config.type == "kinesis":
            # Kinesis shard calculation
            shards = max(1, (msg_config.messages_per_day // 86400 // 1000) + 1)
            cost = shards * PricingService.get_price("messaging", "kinesis_shard")
            reqs["Queue"] = f"Kinesis - {shards} shards"
        
        # DLQ adds minimal cost
        if msg_config.dlq_enabled:
            reqs["DLQ"] = "Enabled"
        
        return cost, reqs
    
    @staticmethod
    def calculate_security_cost(sec_config: SecurityConfig, traffic: TrafficInput) -> tuple[float, dict]:
        """Calculate security costs"""
        cost = 0.0
        reqs = {}
        
        if sec_config.waf_enabled:
            # WAF: 10 rules + request costs
            waf_rules_cost = 10 * PricingService.get_price("security", "waf_rule")
            monthly_requests = traffic.daily_active_users * traffic.api_requests_per_user * 30
            waf_requests_cost = (monthly_requests / 1000000) * PricingService.get_price("security", "waf_request_1m")
            cost += waf_rules_cost + waf_requests_cost
            reqs["WAF"] = "Enabled (10 rules)"
        
        if sec_config.vpn_enabled:
            cost += PricingService.get_price("security", "vpn_connection")
            reqs["VPN"] = "Site-to-Site connection"
        
        if sec_config.ddos_protection:
            cost += PricingService.get_price("security", "shield_advanced")
            reqs["DDoS"] = "AWS Shield Advanced"
        
        if sec_config.ssl_certificates > 0:
            # ACM is free
            reqs["SSL"] = f"{sec_config.ssl_certificates} certificates (ACM)"
        
        if sec_config.secrets_manager:
            # Assume 20 secrets
            secrets_cost = 20 * PricingService.get_price("security", "secrets_manager_secret")
            cost += secrets_cost
            reqs["Secrets"] = "20 secrets managed"
        
        # Compliance costs (amortized monthly)
        for standard in sec_config.compliance:
            standard_lower = standard.lower()
            if standard_lower in ["soc2", "iso27001", "hipaa", "pci_dss"]:
                cost += PricingService.get_price("security", f"{standard_lower}_monthly")
                reqs[f"Compliance"] = f"{standard.upper()} audit"
        
        return cost, reqs
    
    @staticmethod
    def calculate_monitoring_cost(mon_config: MonitoringConfig, instances: int, traffic: TrafficInput) -> tuple[float, dict]:
        """Calculate monitoring costs"""
        cost = 0.0
        reqs = {}
        
        if mon_config.provider == "cloudwatch":
            # CloudWatch costs
            metric_cost = instances * 10 * PricingService.get_price("monitoring", "cloudwatch_metric")
            
            # Log costs (assume 1GB per instance per month)
            log_cost = instances * PricingService.get_price("monitoring", "cloudwatch_log_gb")
            
            cost = metric_cost + log_cost
            reqs["Monitoring"] = f"CloudWatch ({instances} hosts)"
            
        elif mon_config.provider == "datadog":
            cost = instances * PricingService.get_price("monitoring", "datadog_host")
            if mon_config.apm_enabled:
                cost += instances * 50  # Additional APM cost
            reqs["Monitoring"] = f"Datadog ({instances} hosts)"
            
        elif mon_config.provider == "newrelic":
            base_cost = instances * PricingService.get_price("monitoring", "newrelic_host")
            if mon_config.apm_enabled:
                base_cost += instances * PricingService.get_price("monitoring", "newrelic_apm_host")
            cost = base_cost
            reqs["Monitoring"] = f"New Relic ({instances} hosts)"
        
        # Distributed tracing
        if mon_config.distributed_tracing:
            monthly_requests = traffic.daily_active_users * traffic.api_requests_per_user * 30
            trace_cost = (monthly_requests / 1000000) * PricingService.get_price("monitoring", "xray_trace_1m")
            cost += trace_cost
            reqs["Tracing"] = "X-Ray/distributed"
        
        return cost, reqs
    
    @staticmethod
    def calculate_cicd_cost(cicd_config: CICDConfig) -> tuple[float, dict]:
        """Calculate CI/CD costs"""
        cost = 0.0
        reqs = {}
        
        if cicd_config.provider == "github_actions":
            # Assume average 10 minutes per build
            minutes = cicd_config.builds_per_month * 10
            cost = minutes * PricingService.get_price("cicd", "github_actions_linux_minute")
            reqs["CI/CD"] = f"GitHub Actions ({cicd_config.builds_per_month} builds/mo)"
            
        elif cicd_config.provider == "gitlab_ci":
            minutes = cicd_config.builds_per_month * 10
            cost = minutes * PricingService.get_price("cicd", "gitlab_ci_minute")
            reqs["CI/CD"] = f"GitLab CI ({cicd_config.builds_per_month} builds/mo)"
            
        elif cicd_config.provider == "jenkins":
            cost = PricingService.get_price("cicd", "jenkins_m5_large")
            reqs["CI/CD"] = "Jenkins m5.large"
        
        # Container registry
        if cicd_config.container_registry:
            # Assume 50GB of images
            registry_cost = 50 * PricingService.get_price("cicd", "ecr_storage_gb")
            cost += registry_cost
            reqs["Container Registry"] = "50 GB"
        
        # Security scanning
        if cicd_config.security_scanning:
            # Assume 5 active developers
            scan_cost = 5 * PricingService.get_price("cicd", "code_scanning_user")
            cost += scan_cost
            reqs["Security Scan"] = "5 users"
        
        # Artifact storage
        if cicd_config.artifact_storage_gb > 0:
            artifact_cost = cicd_config.artifact_storage_gb * PricingService.get_price("cicd", "artifact_storage_gb")
            cost += artifact_cost
            reqs["Artifacts"] = f"{cicd_config.artifact_storage_gb} GB"
        
        return cost, reqs
    
    @staticmethod
    def calculate_multi_region_cost(mr_config: MultiRegionConfig, base_infra_cost: float) -> tuple[float, dict]:
        """Calculate multi-region costs"""
        if not mr_config.enabled or mr_config.regions <= 1:
            return 0.0, {}
        
        cost = 0.0
        reqs = {}
        
        # Additional regions infrastructure
        additional_regions = mr_config.regions - 1
        region_multiplier = PricingService.get_price("replication", "region_multiplier")
        region_cost = base_infra_cost * region_multiplier * additional_regions
        cost += region_cost
        reqs["Regions"] = f"{mr_config.regions} regions ({mr_config.replication_type})"
        
        # Cross-region data transfer
        if mr_config.cross_region_transfer_gb > 0:
            transfer_cost = mr_config.cross_region_transfer_gb * PricingService.get_price("replication", "cross_region_gb")
            cost += transfer_cost
            reqs["Cross-Region Transfer"] = f"{mr_config.cross_region_transfer_gb} GB/mo"
        
        # Active-active doubles some costs
        if mr_config.replication_type == "active_active":
            cost *= 1.3  # Additional orchestration overhead
            reqs["HA Setup"] = "Active-Active"
        
        return cost, reqs

    @staticmethod
    def calculate_multi_cloud_costs(base_cost_usd: float, currency: str) -> dict:
        """Calculate costs across all cloud providers using database multipliers"""
        multi_cloud = {}
        
        # Calculate cost for each provider
        for provider, multiplier in PricingService.CLOUD_MULTIPLIERS.items():
            provider_cost_usd = base_cost_usd * multiplier
            provider_cost_converted = PricingService.convert(provider_cost_usd, currency)
            multi_cloud[provider] = provider_cost_converted
        
        return multi_cloud
    
    @staticmethod
    def estimate(architecture: ArchitectureType, traffic: TrafficInput, currency: str = "USD") -> EstimationResult:
        # Initialize with zeros
        compute_cost = 0.0
        database_cost = 0.0
        storage_cost = 0.0
        networking_cost = 0.0
        cdn_cost = 0.0
        messaging_cost = 0.0
        security_cost = 0.0
        monitoring_cost = 0.0
        cicd_cost = 0.0
        multi_region_cost = 0.0
        
        infra_reqs = {}
        instances = 1
        
        # Basic logic based on architecture
        if architecture == ArchitectureType.MONOLITH:
            # Monolith scaling logic
            daily_requests = traffic.daily_active_users * traffic.api_requests_per_user
            peak_rps = (daily_requests / 86400) * traffic.peak_traffic_multiplier
            
            rps_per_instance = 40.0 
            instances = max(1, int(peak_rps / rps_per_instance) + 1)
            
            instance_type = "t3.medium"
            compute_cost = instances * PricingService.get_price("compute", instance_type)
            infra_reqs["Compute"] = f"{instances}x {instance_type} EC2 (Peak RPS: {peak_rps:.1f})"
            
            # Database
            database_cost = PricingService.get_price("database", "rds_db.t3.medium")
            infra_reqs["Database"] = "1x db.t3.medium RDS"

        elif architecture == ArchitectureType.MICROSERVICES:
            # Microservices overhead
            services_count = 5
            instances_per_service = max(1, traffic.daily_active_users // 50000)
            instances = services_count * instances_per_service
            compute_cost = instances * PricingService.get_price("compute", "t3.micro")
            infra_reqs["Compute"] = f"{instances}x t3.micro (across {services_count} services)"
            
            database_cost = PricingService.get_price("database", "rds_db.t3.medium") + \
                                    PricingService.get_price("database", "dynamodb_unit") * 10
            infra_reqs["Database"] = "RDS + DynamoDB"

        elif architecture == ArchitectureType.SERVERLESS:
            # Lambda pricing
            requests_per_month = traffic.daily_active_users * traffic.api_requests_per_user * 30
            compute_cost = (requests_per_month / 1000000) * PricingService.get_price("compute", "lambda_1m_requests")
            infra_reqs["Compute"] = f"{requests_per_month:,.0f} Lambda Invocations/mo"
            instances = max(1, int(requests_per_month / 1000000))  # For monitoring calc
            
            database_cost = PricingService.get_price("database", "dynamodb_unit") * 20
            infra_reqs["Database"] = "DynamoDB On-Demand"
        
        else: # Hybrid or other
            instances = max(1, traffic.daily_active_users // 20000)
            compute_cost = instances * PricingService.get_price("compute", "t3.medium")
            infra_reqs["Compute"] = f"{instances}x t3.medium (Hybrid)"
            database_cost = PricingService.get_price("database", "rds_db.t3.medium")

        # Common costs
        # Safe calculation: storage with zero-checks
        storage_gb = max(0.0, (traffic.daily_active_users * traffic.storage_per_user_mb) / 1024)
        storage_cost = storage_gb * PricingService.get_price("storage", "s3_gb")
        infra_reqs["Storage"] = f"{storage_gb:.2f} GB S3"

        networking_cost = PricingService.get_price("networking", "load_balancer")
        
        # Advanced features calculations
        db_addon_cost, db_reqs = EstimationService.calculate_database_cost(traffic, traffic.database, database_cost)
        database_cost = db_addon_cost
        infra_reqs.update(db_reqs)
        
        cdn_cost, cdn_reqs = EstimationService.calculate_cdn_cost(traffic.cdn)
        infra_reqs.update(cdn_reqs)
        
        messaging_cost, msg_reqs = EstimationService.calculate_messaging_cost(traffic.messaging, traffic)
        infra_reqs.update(msg_reqs)
        
        security_cost, sec_reqs = EstimationService.calculate_security_cost(traffic.security, traffic)
        infra_reqs.update(sec_reqs)
        
        monitoring_cost, mon_reqs = EstimationService.calculate_monitoring_cost(traffic.monitoring, instances, traffic)
        infra_reqs.update(mon_reqs)
        
        cicd_cost, cicd_reqs = EstimationService.calculate_cicd_cost(traffic.cicd)
        infra_reqs.update(cicd_reqs)
        
        # Calculate base infrastructure total before multi-region
        base_total = compute_cost + database_cost + storage_cost + networking_cost + cdn_cost + messaging_cost + security_cost + monitoring_cost + cicd_cost
        
        multi_region_cost, mr_reqs = EstimationService.calculate_multi_region_cost(traffic.multi_region, base_total)
        infra_reqs.update(mr_reqs)
        
        # Calculate total in USD first
        total_usd = base_total + multi_region_cost
        
        # Convert all components to target currency and create CostComponent
        monthly_cost = CostComponent(
            compute=PricingService.convert(compute_cost, currency),
            database=PricingService.convert(database_cost, currency),
            storage=PricingService.convert(storage_cost, currency),
            networking=PricingService.convert(networking_cost, currency),
            cdn=PricingService.convert(cdn_cost, currency),
            messaging=PricingService.convert(messaging_cost, currency),
            security=PricingService.convert(security_cost, currency),
            monitoring=PricingService.convert(monitoring_cost, currency),
            cicd=PricingService.convert(cicd_cost, currency),
            multi_region=PricingService.convert(multi_region_cost, currency),
            total=PricingService.convert(total_usd, currency)
        )
        
        yearly_cost = monthly_cost.total * 12
        
        # Projections
        projections = {
            "Year 1": yearly_cost,
            "Year 2": yearly_cost * (1 + traffic.growth_rate_yoy),
            "Year 3": yearly_cost * ((1 + traffic.growth_rate_yoy) ** 2)
        }

        # Multi-Cloud Comparison (using new structured method)
        multi_cloud = EstimationService.calculate_multi_cloud_costs(total_usd, currency)

        # Scaling Scenarios
        scaling_scenarios = {}
        base_users = traffic.daily_active_users
        for scale_label, user_count in [("10k Users", 10000), ("100k Users", 100000), ("1M Users", 1000000)]:
            scale_factor = (user_count / base_users) if base_users > 0 else 0
            scaled_cost_usd = total_usd * (scale_factor ** 0.9) 
            scaling_scenarios[scale_label] = PricingService.convert(scaled_cost_usd, currency)

        # Optimization Suggestions (keeping existing logic)
        optimization_suggestions = []
        compute_usd = compute_cost
        if compute_usd > 50:
            ri_saving_usd = compute_usd * 0.40
            ri_saving = PricingService.convert(ri_saving_usd, currency)
            optimization_suggestions.append({
                "title": "Reserved Instances (1-Year)",
                "saving": f"{PricingService.CURRENCY_SYMBOLS.get(currency, '$')}{ri_saving:,.0f}/mo",
                "description": "Commit to 1-year usage for consistent workloads to save ~40% on compute."
            })

        if architecture in [ArchitectureType.MICROSERVICES, ArchitectureType.HYBRID]:
             spot_saving_usd = compute_usd * 0.70 * 0.3
             spot_saving = PricingService.convert(spot_saving_usd, currency)
             optimization_suggestions.append({
                "title": "Spot Instances",
                "saving": f"{PricingService.CURRENCY_SYMBOLS.get(currency, '$')}{spot_saving:,.0f}/mo",
                "description": "Use Spot instances for stateless microservices to save up to 70%."
            })
        
        storage_usd = storage_cost
        if storage_usd > 20:
             lifecycle_saving_usd = storage_usd * 0.30
             lifecycle_saving = PricingService.convert(lifecycle_saving_usd, currency)
             optimization_suggestions.append({
                "title": "S3 Lifecycle Policies",
                "saving": f"{PricingService.CURRENCY_SYMBOLS.get(currency, '$')}{lifecycle_saving:,.0f}/mo",
                "description": "Move infrequently accessed data to Glacier/Cold storage."
            })

        # Business Metrics
        business_metrics = {}
        
        if traffic.daily_active_users > 0:
            # Safe division: cost per user
            cost_per_user = monthly_cost.total / traffic.daily_active_users if traffic.daily_active_users > 0 else 0
            business_metrics["Infrastructure Cost per User"] = f"{PricingService.CURRENCY_SYMBOLS.get(currency, '$')}{cost_per_user:.4f}/mo"
        
        if traffic.funding_available > 0 and monthly_cost.total > 0:
            funding_converted = PricingService.convert(traffic.funding_available, currency)
            # Safe division: runway calculation
            runway_months = funding_converted / monthly_cost.total if monthly_cost.total > 0 else 0
            if runway_months > 240:  # Cap at 20 years
                business_metrics["Runway"] = "Indefinite (>20 years)"
            else:
                business_metrics["Runway"] = f"{runway_months:.1f} months"
        
        if traffic.revenue_per_user_monthly > 0:
            revenue_per_user_converted = PricingService.convert(traffic.revenue_per_user_monthly, currency)
            if traffic.daily_active_users > 0:
                total_revenue = revenue_per_user_converted * traffic.daily_active_users
                # Safe division: cost as percentage of revenue
                if total_revenue > 0:
                    cost_percent = (monthly_cost.total / total_revenue) * 100
                else:
                    cost_percent = 0
                    
                business_metrics["Infra Cost as % of Revenue"] = f"{cost_percent:.1f}%"
                
                if cost_percent > 100:
                    business_metrics["Profitability"] = "Unprofitable (Infra costs exceed revenue)"
                else:
                    business_metrics["Profitability"] = "Profitable (Infra-wise)"

        return EstimationResult(
            architecture=architecture,
            traffic_input=traffic,
            monthly_cost=monthly_cost,
            yearly_cost=yearly_cost,
            three_year_projection=projections,
            infrastructure_requirements=infra_reqs,
            multi_cloud_costs=multi_cloud,
            scaling_scenarios=scaling_scenarios,
            optimization_suggestions=optimization_suggestions,
            business_metrics=business_metrics
        )
