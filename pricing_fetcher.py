"""
Enhanced pricing fetcher with comprehensive multi-cloud pricing:
- Fetches detailed component pricing from AWS, Azure, GCP, DigitalOcean
- Stores comprehensive pricing breakdowns in MongoDB
- Maintains historical backups and job status tracking
"""
import httpx
import json
import logging
import os
from datetime import datetime
from database import get_database

logger = logging.getLogger(__name__)

class PricingFetcher:
    # API endpoints
    AZURE_API_URL = "https://prices.azure.com/api/retail/prices"
    AWS_API_URL = "https://www.ec2instances.info/instances.json"

    @staticmethod
    async def fetch_aws_prices(client):
        """Fetch comprehensive AWS pricing data"""
        try:
            logger.info("Fetching detailed AWS prices from Vantage...")
            response = await client.get(PricingFetcher.AWS_API_URL, timeout=30.0)
            data = response.json()
            
            pricing = {
                "compute": {},
                "database": {},
                "storage": {},
                "networking": {},
                "cdn": {}
            }
            
            # Extract compute pricing for various instance types
            for instance in data:
                instance_type = instance.get('instance_type')
                region_pricing = instance.get('pricing', {}).get('us-east-1', {}).get('linux', {})
                ondemand = region_pricing.get('ondemand')
                
                if ondemand and instance_type:
                    hourly = float(ondemand)
                    monthly = hourly * 730  # 730 hours/month average
                    
                    # Collect t3 family instances
                    if instance_type in ['t3.micro', 't3.small', 't3.medium', 't3.large', 't3.xlarge']:
                        pricing['compute'][instance_type] = monthly
                    
                    # Collect m5 family instances  
                    elif instance_type in ['m5.large', 'm5.xlarge', 'm5.2xlarge']:
                        pricing['compute'][instance_type] = monthly
                    
                    # Use t3.medium as baseline for RDS estimation
                    if instance_type == 't3.medium':
                        baseline = monthly
                        # RDS is typically 1.5-2x compute cost
                        pricing['database']['rds_db.t3.micro'] = baseline * 0.4
                        pricing['database']['rds_db.t3.medium'] = baseline * 1.6
                        pricing['database']['rds_db.t3.large'] = baseline * 3.2
                        pricing['database']['dynamodb_unit'] = 1.25  # Per WCU/RCU unit
            
            # AWS static pricing (from official pricing pages)
            pricing['storage']['s3_gb'] = 0.023  # S3 Standard
            pricing['storage']['s3_glacier_gb'] = 0.004  # Glacier
            pricing['networking']['alb_hour'] = 0.0225  # ALB per hour
            pricing['networking']['data_transfer_gb'] = 0.09  # First 10TB
            pricing['cdn']['cloudfront_gb'] = 0.085  # CloudFront per GB
            
            logger.info(f"AWS pricing fetched: {len(pricing['compute'])} compute types")
            return pricing
        except Exception as e:
            logger.error(f"Error fetching AWS prices: {e}")
            return None

    @staticmethod
    async def fetch_azure_prices(client):
        """Fetch comprehensive Azure pricing from Retail API"""
        try:
            logger.info("Fetching detailed Azure prices...")
            pricing = {
                "compute": {},
                "database": {},
                "storage": {},
                "networking": {},
                "cdn": {}
            }
            
            # Fetch VM pricing for D-series (most common)
            vm_query = "armRegionName eq 'eastus' and serviceName eq 'Virtual Machines' and priceType eq 'Consumption'"
            response = await client.get(f"{PricingFetcher.AZURE_API_URL}?$filter={vm_query}", timeout=30.0)
            data = response.json()
            
            for item in data.get('Items', [])[:20]:  # Limit to first 20 items
                sku = item.get('skuName', '')
                price = item.get('retailPrice', 0)
                
                # Map Azure VMs to pricing
                if 'D2s v3' in sku or 'D2 v3' in sku:
                    pricing['compute']['d2s_v3'] = float(price) * 730
                elif 'D4s v3' in sku or 'D4 v3' in sku:
                    pricing['compute']['d4s_v3'] = float(price) * 730
                elif 'B1s' in sku:
                    pricing['compute']['b1s'] = float(price) * 730
            
            # Azure static pricing (from official pricing)
            pricing['database']['sql_basic'] = 15.00  # Basic tier monthly
            pricing['database']['sql_standard_s2'] = 150.00  # Standard S2
            pricing['database']['cosmos_ru_100'] = 5.84  # 100 RU/s
            pricing['storage']['blob_hot_gb'] = 0.0184  # Hot tier
            pricing['storage']['blob_cool_gb'] = 0.01  # Cool tier
            pricing['networking']['load_balancer'] = 18.26  # Basic LB monthly
            pricing['cdn']['cdn_gb'] = 0.081  # Azure CDN per GB
            
            logger.info(f"Azure pricing fetched: {len(pricing['compute'])} compute types")
            return pricing
        except Exception as e:
            logger.error(f"Error fetching Azure prices: {e}")
            return None

    @staticmethod
    async def fetch_gcp_prices(client):
        """Fetch GCP pricing (using static official pricing)"""
        logger.info("Loading GCP static pricing...")
        # GCP official pricing (updated Q4 2024)
        return {
            "compute": {
                "e2-micro": 6.11,  # Monthly
                "e2-small": 12.23,
                "e2-medium": 24.45,
                "e2-standard-2": 48.90,
                "n1-standard-1": 24.27,
                "n1-standard-2": 48.54,
            },
            "database": {
                "cloud_sql_micro": 7.67,  # db-f1-micro
                "cloud_sql_small": 25.00,  # db-g1-small  
                "cloud_sql_standard": 107.30,  # db-n1-standard-1
                "firestore_gb": 0.18,  # Per GB
            },
            "storage": {
                "standard_gb": 0.020,  # Cloud Storage Standard
                "nearline_gb": 0.010,  # Nearline
                "coldline_gb": 0.004,  # Coldline
            },
            "networking": {
                "load_balancer": 18.26,  # Cloud Load Balancer
                "egress_gb": 0.12,  # First tier egress
            },
            "cdn": {
                "cloud_cdn_gb": 0.08,  # Cloud CDN
            }
        }

    @staticmethod
    async def fetch_digitalocean_prices(client):
        """Fetch DigitalOcean pricing (static from documentation)"""
        logger.info("Loading DigitalOcean static pricing...")
        # DigitalOcean official pricing (updated Q4 2024)
        return {
            "compute": {
                "basic_1gb": 6.00,  # Basic droplet 1GB
                "basic_2gb": 12.00,  # Basic droplet 2GB
                "basic_4gb": 24.00,  # Basic droplet 4GB
                "general_2gb": 18.00,  # General Purpose 2GB
                "general_4gb": 36.00,  # General Purpose 4GB
            },
            "database": {
                "managed_db_1gb": 15.00,  # Managed Database 1GB  
                "managed_db_2gb": 30.00,  # Managed Database 2GB
                "managed_db_4gb": 60.00,  # Managed Database 4GB
            },
            "storage": {
                "spaces_gb": 0.02,  # Spaces (S3-compatible)
                "block_storage_gb": 0.10,  # Block Storage
            },
            "networking": {
                "load_balancer": 12.00,  # Load Balancer monthly
                "bandwidth_gb": 0.01,  # Overage bandwidth
            },
            "cdn": {
                "cdn_gb": 0.01,  # CDN bandwidth
            }
        }

    @staticmethod
    async def fetch_hetzner_prices(client):
        """Jet Hetzner pricing (static from documentation)"""
        logger.info("Loading Hetzner static pricing...")
        return {
            "compute": {
                "cx11": 3.29,  # 1 vCPU, 2GB RAM
                "cx21": 5.83,  # 2 vCPU, 4GB RAM
                "cx31": 11.17,  # 2 vCPU, 8GB RAM
                "cx41": 21.34,  #  4 vCPU, 16GB RAM
            },
            "database": {
                "managed_postgresql_1gb": 10.00,
                "managed_mysql_1gb": 10.00,
            },
            "storage": {
                "volume_gb": 0.04,  # Block storage per GB
                "snapshot_gb": 0.01,  # Snapshot per GB
            },
            "networking": {
                "load_balancer": 4.90,  # Load Balancer monthly
                "traffic_gb": 0.011,  # Outbound traffic
            },
            "cdn": {}
        }

    @staticmethod
    async def fetch_other_provider_prices():
        """Fetch pricing for remaining providers (static)"""
        logger.info("Loading pricing for other providers...")
        return {
            "Linode": {
                "compute": {"nanode_1gb": 5.00, "linode_2gb": 10.00, "linode_4gb": 20.00},
                "database": {"managed_db_1gb": 15.00},
                "storage": {"block_storage_gb": 0.10},
                "networking": {"lb_monthly": 10.00},
                "cdn": {}
            },
            "Vultr": {
                "compute": {"vc2_1c_1gb": 6.00, "vc2_2c_4gb": 18.00},
                "database": {"managed_db_1gb": 15.00},
                "storage": {"block_storage_gb": 0.10},
                "networking": {},
                "cdn": {}
            },
            # Indian Providers
            "Tata IZO": {
                "compute": {"small": 15.00, "medium": 30.00},
                "database": {},
                "storage": {"storage_gb": 0.03},
                "networking": {},
                "cdn": {}
            },
            "CtrlS": {
                "compute": {"small": 18.00, "medium": 35.00},
                "database": {},
                "storage": {"storage_gb": 0.03},
                "networking": {},
                "cdn": {}
            },
            "Netmagic": {
                "compute": {"small": 20.00, "medium": 40.00},
                "database": {},
                "storage": {"storage_gb": 0.04},
                "networking": {},
                "cdn": {}
            },
            "Yotta": {
                "compute": {"small": 16.00, "medium": 32.00},
                "database": {},
                "storage": {"storage_gb": 0.03},
                "networking": {},
                "cdn": {}
            },
            # Regional providers  
            "Alibaba Cloud": {
                "compute": {"ecs.t5-lc1m1.small": 4.50, "ecs.t5-lc1m2.small": 9.00},
                "database": {},
                "storage": {"oss_gb": 0.02},
                "networking": {},
                "cdn": {"cdn_gb": 0.04}
            },
            "OVHcloud": {
                "compute": {"d2-2": 13.00, "d2-4": 24.00},
                "database": {},
                "storage": {"object_storage_gb": 0.01},
                "networking": {},
                "cdn": {}
            },
            "Scaleway": {
                "compute": {"dev1_s": 7.99, "dev1_m": 15.99},
                "database": {},
                "storage": {"object_storage_gb": 0.01},
                "networking": {},
                "cdn": {}
            },
            "Vercel": {
                "compute": {"hobby": 0.00, "pro": 20.00},
                "database": {},
                "storage": {},
                "networking": {},
                "cdn": {}
            },
            "Oracle Cloud": {
                "compute": {"vm_standard_e2_1": 40.00, "vm_standard_e2_2": 80.00},
                "database": {"autonomous_db": 295.00},
                "storage": {"object_storage_gb": 0.0255},
                "networking": {},
                "cdn": {}
            },
            "IBM Cloud": {
                "compute": {"bx2_2x8": 65.00, "bx2_4x16": 130.00},
                "database": {"databases_postgresql": 30.00},
                "storage": {"object_storage_gb": 0.023},
                "networking": {},
                "cdn": {}
            }
        }

    @staticmethod
    async def fetch_currency_rates(client):
        """Fetch real-time currency exchange rates"""
        try:
            logger.info("Fetching currency exchange rates...")
            response = await client.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=15.0)
            data = response.json()
            
            if data and 'rates' in data:
                rates = data['rates']
                supported_currencies = [
                    "USD", "CAD", "MXN", "BRL", "ARS", "EUR", "GBP", "CHF", 
                    "INR", "JPY", "CNY", "KRW", "SGD", "HKD", "AUD", "NZD",
                    "AED", "SAR", "ZAR"
                ]
                
                currency_rates = {"USD": 1.0}
                for currency in supported_currencies:
                    if currency != "USD" and currency in rates:
                        currency_rates[currency] = rates[currency]
                
                logger.info(f"Fetched {len(currency_rates)} currency rates")
                return currency_rates
            return None
        except Exception as e:
            logger.error(f"Error fetching currency rates: {e}")
            return None

    @staticmethod
    async def archive_current_pricing(db):
        """Archive current pricing to history (keep only 2 backups max)"""
        try:
            current = await db.pricing.find_one({"_id": "latest_pricing"})
            if current:
                # Remove _id and add archive timestamp
                current.pop("_id", None)
                current["archived_at"] = datetime.now().isoformat()
                
                # Get count of historical backups
                history_count = await db.pricing_history.count_documents({})
                
                # If we already have 2 backups, remove the oldest one
                if history_count >= 2:
                    # Sort by archived_at and delete the oldest
                    oldest = await db.pricing_history.find_one(
                        sort=[("archived_at", 1)]
                    )
                    if oldest:
                        await db.pricing_history.delete_one({"_id": oldest["_id"]})
                        logger.info(f"Removed oldest backup to maintain max 2 copies")
                
                # Insert current pricing as new backup
                result = await db.pricing_history.insert_one(current)
                logger.info(f"Archived pricing backup {result.inserted_id}. Total backups: {history_count + 1} (capped at 2)")
                return True
        except Exception as e:
            logger.error(f"Error archiving pricing: {e}")
        return False

    @staticmethod
    async def track_job_status(db, status: str, error: str = None, metadata: dict = None):
        """Track job execution status for admin dashboard"""
        try:
            current_time = datetime.now()
            job_data = {
                "_id": "pricing_job_status",
                "last_run": current_time.isoformat(),
                "last_run_timestamp": current_time.timestamp(),
                "status": status,  # "success" or "failed"
                "duration_seconds": None,
            }
            
            if error:
                job_data["error"] = error
                job_data["error_message"] = error
            else:
                job_data["error"] = None
            
            if metadata:
                job_data.update(metadata)
            
            await db.job_status.update_one(
                {"_id": "pricing_job_status"},
                {"$set": job_data},
                upsert=True
            )
            
            status_msg = f"Job Status: {status} | Last run: {job_data['last_run']}"
            if metadata:
                status_msg += f" | Sources: {metadata.get('sources_fetched', 0)} | Currencies: {metadata.get('currencies_updated', 0)}"
            logger.info(status_msg)
            return True
        except Exception as e:
            logger.error(f"Error tracking job status: {e}")
        return False

    @staticmethod
    async def fetch_latest_prices():
        """
        Fetches comprehensive multi-cloud pricing and updates MongoDB
        """
        logger.info("Starting comprehensive multi-cloud price fetch...")
        
        try:
            async with httpx.AsyncClient() as client:
                # Fetch prices from all sources
                aws_pricing = await PricingFetcher.fetch_aws_prices(client)
                azure_pricing = await PricingFetcher.fetch_azure_prices(client)
                gcp_pricing = await PricingFetcher.fetch_gcp_prices(client)
                digitalocean_pricing = await PricingFetcher.fetch_digitalocean_prices(client)
                hetzner_pricing = await PricingFetcher.fetch_hetzner_prices(client)
                other_providers = await PricingFetcher.fetch_other_provider_prices()
                currency_rates = await PricingFetcher.fetch_currency_rates(client)
                
                # Default currency rates if fetch failed
                if not currency_rates:
                    currency_rates = {
                        "USD": 1.0, "INR": 84.0, "EUR": 0.92, "GBP": 0.79,
                        "JPY": 150.0, "CNY": 7.2, "AUD": 1.52
                    }
                
                # Build comprehensive pricing data structure
                pricing_data = {
                    "providers": {
                        "AWS": aws_pricing or {},
                        "Azure": azure_pricing or {},
                        "GCP": gcp_pricing or {},
                        "DigitalOcean": digitalocean_pricing or {},
                        "Hetzner": hetzner_pricing or {},
                        **other_providers
                    },
                    "currency_rates": currency_rates,
                    "meta": {
                        "last_updated": datetime.now().isoformat(),
                        "sources": ["AWS-Vantage", "Azure-Retail-API", "ExchangeRate-API", "Static-Documentation"],
                        "version": "2.0"
                    }
                }
                
                # Save to MongoDB with backup
                db = await get_database()
                if db is not None:
                    try:
                        # Archive current version
                        await PricingFetcher.archive_current_pricing(db)
                        
                        # Update current pricing
                        result = await db.pricing.update_one(
                            {"_id": "latest_pricing"},
                            {"$set": pricing_data},
                            upsert=True
                        )
                        
                        if result.matched_count > 0 or result.upserted_id:
                            # Track success
                            total_providers = len(pricing_data["providers"])
                            job_metadata = {
                                "sources_fetched": len(pricing_data["meta"]["sources"]),
                                "currencies_updated": len(currency_rates),
                                "providers_updated": total_providers,
                                "pricing_version": "2.0"
                            }
                            
                            await PricingFetcher.track_job_status(
                                db, 
                                "success",
                                metadata=job_metadata
                            )
                            
                            logger.info(f"✅ Successfully updated comprehensive pricing. Providers: {total_providers}, Currencies: {len(currency_rates)}")
                            return True
                        else:
                            logger.warning("Update operation completed but no documents were modified")
                            await PricingFetcher.track_job_status(
                                db, 
                                "warning",
                                error="No documents were updated"
                            )
                            return False
                            
                    except Exception as db_error:
                        logger.error(f"Database operation failed: {db_error}")
                        await PricingFetcher.track_job_status(
                            db, 
                            "failed", 
                            error=str(db_error)
                        )
                        return False
                else:
                    logger.error("Database not available")
                    return False
                
        except Exception as e:
            logger.error(f"Failed to fetch prices: {str(e)}")
            try:
                db = await get_database()
                if db:
                    await PricingFetcher.track_job_status(db, "failed", error=str(e))
            except:
                pass
            return False
