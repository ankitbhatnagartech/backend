import json
import os
import logging

logger = logging.getLogger(__name__)

class PricingService:
    PRICING_FILE = "pricing_data.json"

    # Real-world pricing approximations (AWS us-east-1, 2025 estimates)
    # These serve as defaults/fallbacks
    PRICING = {
        "compute": {
            "t3.micro": 7.50,    # ~$0.0104/hr * 730
            "t3.medium": 30.40,  # ~$0.0416/hr * 730
            "t3.large": 60.80,   # ~$0.0832/hr * 730
            "lambda_1m_requests": 0.20, # Standard pricing
            "fargate_vcpu": 29.0 # ~$0.04/vCPU/hr
        },
        "database": {
            "rds_db.t3.micro": 30.0, # Updated 2025: Instance + Storage (~$0.041/hr + storage)
            "rds_db.t3.medium": 60.0, # ~$0.082/hr
            "rds_db.t3.large": 121.0,
            "dynamodb_unit": 0.25, # WCU/RCU blended estimate
            "firestore_read_1m": 0.06,
            "firestore_write_1m": 0.18,
            "read_replica": 55.0, # Additional cost per replica
            "backup_gb": 0.095 # Backup storage
        },
        "storage": {
            "s3_gb": 0.023,
            "ebs_gb": 0.10
        },
        "networking": {
            "load_balancer": 16.20, # ALB minimum ~$0.0225/hr
            "data_transfer_gb": 0.09
        },
        "cache": {
            "redis_t4g_micro": 11.0,
            "redis_t4g_small": 24.0,
            "redis_t4g_medium": 48.0,
            "memcached_t4g_micro": 10.0,
            "memcached_t4g_small": 22.0
        },
        "cdn": {
            "cloudfront_gb": 0.085,
            "cloudfront_edge_function_1m": 0.60,
            "cloudflare_gb": 0.01,
            "cloudflare_workers_1m": 0.50,
            "akamai_gb": 0.12,
            "video_streaming_multiplier": 1.5
        },
        "messaging": {
            "sqs_1m_requests": 0.40,
            "sns_1m_notifications": 0.50,
            "kafka_broker": 400.0, # Updated 2025: AWS MSK m5.large broker
            "rabbitmq_m5_large": 140.0,
            "kinesis_shard": 18.0,
            "eventbridge_1m_events": 1.00
        },
        "security": {
            "waf_rule": 1.0,
            "waf_request_1m": 0.60,
            "vpn_connection": 36.50,
            "shield_advanced": 3000.0,
            "acm_certificate": 0.0,  # Free
            "secrets_manager_secret": 0.40,
            "secrets_api_call_10k": 0.05,
            "soc2_audit_monthly": 1250.0,  # $15k/year amortized
            "iso27001_monthly": 1667.0,  # $20k/year amortized
            "hipaa_monthly": 2083.0,  # $25k/year amortized
            "pci_dss_monthly": 1500.0  # $18k/year amortized
        },
        "monitoring": {
            "cloudwatch_metric": 0.30,
            "cloudwatch_log_gb": 0.50,
            "cloudwatch_dashboard": 3.0,
            "datadog_host": 15.0,
            "datadog_log_gb": 1.70,
            "newrelic_host": 10.0,
            "newrelic_apm_host": 99.0,
            "xray_trace_1m": 5.0,
            "xray_retrieved_1m": 0.50,
            "alert_channel": 0.0  # Usually free
        },
        "cicd": {
            "github_actions_linux_minute": 0.008,
            "github_actions_windows_minute": 0.016,
            "gitlab_ci_minute": 0.01,
            "jenkins_m5_large": 140.0,
            "ecr_storage_gb": 0.10,
            "acr_storage_gb": 0.167,
            "docker_hub_team": 7.0,
            "code_scanning_user": 21.0,
            "artifact_storage_gb": 0.25
        },
        "replication": {
            "cross_region_gb": 0.02,
            "vpc_peering_gb": 0.01,
            "region_multiplier": 0.85  # Additional regions cost ~85% of primary
        }
    }

    @classmethod
    async def load_dynamic_prices(cls):
        """Loads pricing from MongoDB if available."""
        from database import get_database
        
        try:
            logger.info("Attempting to load dynamic pricing from database...")
            db = await get_database()
            if db is not None:
                data = await db.pricing.find_one({"_id": "latest_pricing"})
                if data:
                    # Update PRICING dict with loaded data
                    categories_updated = []
                    for category, items in data.items():
                        if category in cls.PRICING and isinstance(items, dict):
                            cls.PRICING[category].update(items)
                            categories_updated.append(category)
                        elif category == "multi_cloud":
                            logger.info(f"Loading multi_cloud multipliers from DB: {items}")
                            cls.CLOUD_MULTIPLIERS.update(items)
                            categories_updated.append("multi_cloud")
                            logger.info(f"CLOUD_MULTIPLIERS after update: {cls.CLOUD_MULTIPLIERS}")
                        elif category == "currency_rates":
                            cls.CURRENCY_RATES.update(items)
                            categories_updated.append("currency_rates")
                            
                    meta = data.get('meta', {})
                    logger.info(f"✅ Loaded dynamic pricing from MongoDB")
                    logger.info(f"   Source: {meta.get('sources', 'Unknown')}")
                    logger.info(f"   Last Updated: {meta.get('last_updated', 'Unknown')}")
                    logger.info(f"   Categories Updated: {categories_updated}")
                else:
                    logger.warning("❌ No pricing data found in MongoDB, using defaults.")
            else:
                logger.warning("❌ Database not available, using default pricing.")
        except Exception as e:
            logger.error(f"❌ Failed to load dynamic pricing from DB: {e}")
            import traceback
            logger.error(traceback.format_exc())



    CURRENCY_RATES = {
        # Americas
        "USD": 1.0,
        "CAD": 1.35,
        "MXN": 17.0,
        "BRL": 5.0,
        "ARS": 350.0,
        "CLP": 900.0,
        "COP": 4000.0,
        "PEN": 3.7,
        
        # Europe
        "EUR": 0.92,
        "GBP": 0.79,
        "CHF": 0.88,
        "SEK": 10.5,
        "NOK": 10.8,
        "DKK": 6.9,
        "PLN": 4.0,
        "CZK": 23.0,
        "HUF": 360.0,
        "RON": 4.6,
        "BGN": 1.8,
        "HRK": 6.9,
        "TRY": 32.0,
        "RUB": 92.0,
        
        # Asia-Pacific
        "INR": 84.0,
        "JPY": 150.0,
        "CNY": 7.2,
        "KRW": 1320.0,
        "SGD": 1.34,
        "HKD": 7.8,
        "TWD": 31.5,
        "THB": 35.0,
        "MYR": 4.5,
        "IDR": 15700.0,
        "PHP": 56.0,
        "VND": 24500.0,
        "PKR": 278.0,
        "BDT": 110.0,
        "LKR": 305.0,
        "AUD": 1.52,
        "NZD": 1.68,
        
        # Middle East & Africa
        "AED": 3.67,
        "SAR": 3.75,
        "QAR": 3.64,
        "KWD": 0.31,
        "BHD": 0.38,
        "ILS": 3.65,
        "EGP": 49.0,
        "ZAR": 18.5,
        "NGN": 1550.0,
        "KES": 129.0
    }

    CURRENCY_SYMBOLS = {
        # Americas
        "USD": "$",
        "CAD": "C$",
        "MXN": "Mex$",
        "BRL": "R$",
        "ARS": "ARS$",
        "CLP": "CLP$",
        "COP": "COL$",
        "PEN": "S/",
        
        # Europe
        "EUR": "€",
        "GBP": "£",
        "CHF": "CHF",
        "SEK": "kr",
        "NOK": "kr",
        "DKK": "kr",
        "PLN": "zł",
        "CZK": "Kč",
        "HUF": "Ft",
        "RON": "lei",
        "BGN": "лв",
        "HRK": "kn",
        "TRY": "₺",
        "RUB": "₽",
        
        # Asia-Pacific
        "INR": "₹",
        "JPY": "¥",
        "CNY": "¥",
        "KRW": "₩",
        "SGD": "S$",
        "HKD": "HK$",
        "TWD": "NT$",
        "THB": "฿",
        "MYR": "RM",
        "IDR": "Rp",
        "PHP": "₱",
        "VND": "₫",
        "PKR": "₨",
        "BDT": "৳",
        "LKR": "Rs",
        "AUD": "A$",
        "NZD": "NZ$",
        
        # Middle East & Africa
        "AED": "د.إ",
        "SAR": "﷼",
        "QAR": "ر.ق",
        "KWD": "د.ك",
        "BHD": "د.ب",
        "ILS": "₪",
        "EGP": "£",
        "ZAR": "R",
        "NGN": "₦",
        "KES": "KSh"
    }

    # Multipliers relative to AWS (Extended to 17 providers)
    CLOUD_MULTIPLIERS = {
        # Major Global
        "AWS": 1.0,
        "Azure": 1.05,  # Slightly premium for enterprise features
        "GCP": 0.95,    # Sustained use discounts
        "Oracle Cloud": 0.90,  # Competitive enterprise pricing
        "IBM Cloud": 1.10,  # Premium for enterprise/mainframe
        
        # Developer-Focused
        "DigitalOcean": 0.60,  # Simple, developer-friendly
        "Linode": 0.65,  # Predictable pricing
        "Vultr": 0.62,  # Aggressive pricing
        "Hetzner": 0.50,  # Very cost-effective
        
        # Indian Providers
        "Tata IZO": 0.85,  # Competitive in Indian market
        "CtrlS": 0.80,  # Cost-effective Indian option
        "Netmagic": 0.90,  # Managed services premium  
        "Yotta": 0.75,  # Competitive hyperscale pricing
        
        # Regional/Specialized
        "Alibaba Cloud": 0.70,  # Competitive in APAC
        "OVHcloud": 0.55,  # European value leader
        "Scaleway": 0.58,  # Competitive European pricing
        "Vercel": 1.25  # Premium for managed edge/serverless
    }

    @staticmethod
    def get_price(category: str, item: str) -> float:
        return PricingService.PRICING.get(category, {}).get(item, 0.0)

    @staticmethod
    def convert(amount_usd: float, target_currency: str) -> float:
        rate = PricingService.CURRENCY_RATES.get(target_currency.upper(), 1.0)
        return amount_usd * rate
