from schemas import TrafficInput, ArchitectureType, EstimationResult, CostComponent
from pricing_service import PricingService

class EstimationService:
    @staticmethod
    def estimate(architecture: ArchitectureType, traffic: TrafficInput, currency: str = "USD") -> EstimationResult:
        # Initialize with zeros
        compute_cost = 0.0
        database_cost = 0.0
        storage_cost = 0.0
        networking_cost = 0.0
        infra_reqs = {}
        
        # ... (calculation logic remains same, it produces USD) ...
        
        # Basic logic based on architecture
        if architecture == ArchitectureType.MONOLITH:
            # Monolith scaling logic
            # Assume t3.medium can handle ~50 RPS comfortably
            # DAU * Requests / 86400 * Peak = Peak RPS
            daily_requests = traffic.daily_active_users * traffic.api_requests_per_user
            peak_rps = (daily_requests / 86400) * traffic.peak_traffic_multiplier
            
            # Capacity per instance (conservative)
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
            services_count = 5 # Assumption for MVP
            instances_per_service = max(1, traffic.daily_active_users // 50000)
            total_instances = services_count * instances_per_service
            compute_cost = total_instances * PricingService.get_price("compute", "t3.micro")
            infra_reqs["Compute"] = f"{total_instances}x t3.micro (across {services_count} services)"
            
            database_cost = PricingService.get_price("database", "rds_db.t3.medium") + \
                                    PricingService.get_price("database", "dynamodb_unit") * 10
            infra_reqs["Database"] = "RDS + DynamoDB"

        elif architecture == ArchitectureType.SERVERLESS:
            # Lambda pricing
            requests_per_month = traffic.daily_active_users * traffic.api_requests_per_user * 30
            compute_cost = (requests_per_month / 1000000) * PricingService.get_price("compute", "lambda_1m_requests")
            infra_reqs["Compute"] = f"{requests_per_month} Lambda Invocations/mo"
            
            database_cost = PricingService.get_price("database", "dynamodb_unit") * 20
            infra_reqs["Database"] = "DynamoDB On-Demand"
        
        else: # Hybrid or other
             # Fallback simple logic
            instances = max(1, traffic.daily_active_users // 20000)
            compute_cost = instances * PricingService.get_price("compute", "t3.medium")
            infra_reqs["Compute"] = f"{instances}x t3.medium (Hybrid)"
            database_cost = PricingService.get_price("database", "rds_db.t3.medium")


        # Common costs
        storage_gb = (traffic.daily_active_users * traffic.storage_per_user_mb) / 1024
        storage_cost = storage_gb * PricingService.get_price("storage", "s3_gb")
        infra_reqs["Storage"] = f"{storage_gb:.2f} GB S3"

        networking_cost = PricingService.get_price("networking", "load_balancer")
        
        # Calculate total in USD first
        total_usd = compute_cost + database_cost + storage_cost + networking_cost
        
        # Convert all components to target currency and create CostComponent
        monthly_cost = CostComponent(
            compute=PricingService.convert(compute_cost, currency),
            database=PricingService.convert(database_cost, currency),
            storage=PricingService.convert(storage_cost, currency),
            networking=PricingService.convert(networking_cost, currency),
            total=PricingService.convert(total_usd, currency)
        )
        
        yearly_cost = monthly_cost.total * 12
        
        # Projections
        projections = {
            "Year 1": yearly_cost,
            "Year 2": yearly_cost * (1 + traffic.growth_rate_yoy),
            "Year 3": yearly_cost * ((1 + traffic.growth_rate_yoy) ** 2)
        }

        # Multi-Cloud Comparison
        multi_cloud = {}
        for provider, multiplier in PricingService.CLOUD_MULTIPLIERS.items():
            cost_usd = total_usd * multiplier
            multi_cloud[provider] = PricingService.convert(cost_usd, currency)

        # Scaling Scenarios (Simplified linear-ish scaling for MVP)
        scaling_scenarios = {}
        base_users = traffic.daily_active_users
        for scale_label, user_count in [("10k Users", 10000), ("100k Users", 100000), ("1M Users", 1000000)]:
            # Rough approximation: Scale cost proportional to user count, but with some efficiency gain (0.9 exponent)
            scale_factor = (user_count / base_users) if base_users > 0 else 0
            scaled_cost_usd = total_usd * (scale_factor ** 0.9) 
            scaling_scenarios[scale_label] = PricingService.convert(scaled_cost_usd, currency)

        # Optimization Suggestions
        optimization_suggestions = []
        
        # 1. Reserved Instances (assuming 40% saving on compute)
        compute_usd = monthly_cost.compute / PricingService.convert(1, currency) # Back to USD roughly
        if compute_usd > 50:
            ri_saving_usd = compute_usd * 0.40
            ri_saving = PricingService.convert(ri_saving_usd, currency)
            optimization_suggestions.append({
                "title": "Reserved Instances (1-Year)",
                "saving": f"{PricingService.CURRENCY_SYMBOLS.get(currency, '$')}{ri_saving:,.0f}/mo",
                "description": "Commit to 1-year usage for consistent workloads to save ~40% on compute."
            })

        # 2. Spot Instances (for stateless/batch workloads)
        if architecture in [ArchitectureType.MICROSERVICES, ArchitectureType.HYBRID]:
             spot_saving_usd = compute_usd * 0.70 * 0.3 # Assuming 30% of fleet can be spot
             spot_saving = PricingService.convert(spot_saving_usd, currency)
             optimization_suggestions.append({
                "title": "Spot Instances",
                "saving": f"{PricingService.CURRENCY_SYMBOLS.get(currency, '$')}{spot_saving:,.0f}/mo",
                "description": "Use Spot instances for stateless microservices to save up to 70%."
            })
        
        # 3. Storage Lifecycle
        storage_usd = monthly_cost.storage / PricingService.convert(1, currency)
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
        
        # Cost per User
        if traffic.daily_active_users > 0:
            cost_per_user = monthly_cost.total / traffic.daily_active_users
            business_metrics["Infrastructure Cost per User"] = f"{PricingService.CURRENCY_SYMBOLS.get(currency, '$')}{cost_per_user:.4f}/mo"
        
        # Runway
        if traffic.funding_available > 0 and monthly_cost.total > 0:
            funding_curr = PricingService.convert(traffic.funding_available, currency) # Assuming input is USD, convert to display
            # Wait, actually let's assume input is in the selected currency for simplicity in frontend, 
            # OR assume input is USD. Let's assume input is USD for consistency with other inputs.
            funding_converted = PricingService.convert(traffic.funding_available, currency)
            runway_months = funding_converted / monthly_cost.total
            business_metrics["Runway"] = f"{runway_months:.1f} months"
        
        # Break-even
        if traffic.revenue_per_user_monthly > 0:
            revenue_per_user_converted = PricingService.convert(traffic.revenue_per_user_monthly, currency)
            # Simple break-even: Fixed costs are low in cloud, mostly variable. 
            # But let's assume the total cost is the "burn" at this scale.
            # Profit = (Revenue/User * Users) - Cost
            # This is tricky because cost scales with users.
            # Let's just show % of Revenue
            if traffic.daily_active_users > 0:
                total_revenue = revenue_per_user_converted * traffic.daily_active_users
                cost_percent = (monthly_cost.total / total_revenue) * 100
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
