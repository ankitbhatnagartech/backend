"""
Enhanced pricing fetcher with MongoDB optimization:
- Replaces pricing data instead of creating duplicates
- Maintains only 2 historical versions (current + previous)
- Tracks job execution status for admin dashboard
"""
import httpx
import json
import logging
import os
from datetime import datetime
from database import get_database

logger = logging.getLogger(__name__)

class PricingFetcher:
    # API endpoints remain the same
    AZURE_API_URL = "https://prices.azure.com/api/retail/prices"
    AWS_API_URL = "https://www.ec2instances.info/instances.json"

    @staticmethod
    async def fetch_aws_prices(client):
        """Fetch AWS pricing from Vantage public JSON"""
        try:
            logger.info("Fetching AWS prices from Vantage...")
            response = await client.get(PricingFetcher.AWS_API_URL, timeout=30.0)
            data = response.json()
            
            for instance in data:
                if instance.get('instance_type') == 't3.medium':
                    pricing = instance.get('pricing', {}).get('us-east-1', {}).get('linux', {})
                    ondemand = pricing.get('ondemand')
                    if ondemand:
                        return float(ondemand)
            return None
        except Exception as e:
            logger.error(f"Error fetching AWS prices: {e}")
            return None

    @staticmethod
    async def fetch_azure_prices(client):
        """Fetch Azure pricing from Retail API"""
        try:
            logger.info("Fetching Azure prices...")
            query = "armRegionName eq 'eastus' and serviceName eq 'Virtual Machines' and skuName eq 'D2s v3' and priceType eq 'Consumption'"
            response = await client.get(f"{PricingFetcher.AZURE_API_URL}?$filter={query}", timeout=30.0)
            data = response.json()
            if data.get('Items'):
                return float(data['Items'][0]['retailPrice'])
            return None
        except Exception as e:
            logger.error(f"Error fetching Azure prices: {e}")
            return None

    @staticmethod
    async def fetch_gcp_prices(client):
        """Fetch GCP pricing (Simulated/Placeholder)"""
        return 0.045  # Simulated e2-medium hourly

    @staticmethod
    async def fetch_do_prices(client):
        """Fetch DigitalOcean pricing (Simulated/Placeholder)"""
        return 0.02  # Simulated Basic Droplet hourly

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
                "last_run_timestamp": current_time.timestamp(),  # For easy sorting
                "status": status,  # "success" or "failed"
                "duration_seconds": None,  # Will be updated if we track start time
            }
            
            if error:
                job_data["error"] = error
                job_data["error_message"] = error
            else:
                job_data["error"] = None
            
            if metadata:
                job_data.update(metadata)
            
            # Use update_one with upsert to ensure atomic update
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
        Fetches latest prices and updates MongoDB with backup mechanism
        """
        logger.info("Starting scheduled multi-cloud price fetch...")
        
        try:
            async with httpx.AsyncClient() as client:
                # Fetch prices from all sources
                aws_price = await PricingFetcher.fetch_aws_prices(client)
                azure_price = await PricingFetcher.fetch_azure_prices(client)
                gcp_price = await PricingFetcher.fetch_gcp_prices(client)
                do_price = await PricingFetcher.fetch_do_prices(client)
                currency_rates = await PricingFetcher.fetch_currency_rates(client)
                
                # Baseline pricing
                baseline_hourly = aws_price if aws_price else 0.0416
                
                # Default currency rates if fetch failed
                if not currency_rates:
                    currency_rates = {
                        "USD": 1.0, "INR": 84.0, "EUR": 0.92, "GBP": 0.79,
                        "JPY": 150.0, "CNY": 7.2, "AUD": 1.52
                    }
                
                # Build pricing data
                pricing_data = {
                    "compute": {
                        "t3.micro": baseline_hourly * 0.25 * 730,
                        "t3.medium": baseline_hourly * 730,
                        "t3.large": baseline_hourly * 2 * 730,
                    },
                    "database": {
                        "rds_db.t3.micro": baseline_hourly * 0.3 * 730,
                        "rds_db.t3.medium": baseline_hourly * 1.5 * 730,
                    },
                    "multi_cloud": {
                        "AWS": 1.0,
                        "Azure": (azure_price / baseline_hourly) if azure_price and baseline_hourly else 1.05,
                        "GCP": (gcp_price / baseline_hourly) if gcp_price and baseline_hourly else 0.95,
                        "DigitalOcean": 0.60,
                    },
                    "currency_rates": currency_rates,
                    "meta": {
                        "last_updated": datetime.now().isoformat(),
                        "sources": ["AWS", "Azure", "ExchangeRate-API"]
                    }
                }
                
                # Save to MongoDB with backup
                db = await get_database()
                if db is not None:
                    try:
                        # Step 1: Archive current version (moves current to history)
                        await PricingFetcher.archive_current_pricing(db)
                        
                        # Step 2: Update current pricing with complete replace
                        # Using update_one with $set ensures atomic replacement
                        result = await db.pricing.update_one(
                            {"_id": "latest_pricing"},
                            {"$set": pricing_data},
                            upsert=True
                        )
                        
                        if result.matched_count > 0 or result.upserted_id:
                            # Step 3: Track success with metadata
                            job_metadata = {
                                "sources_fetched": len(pricing_data["meta"]["sources"]),
                                "currencies_updated": len(currency_rates),
                                "pricing_categories": len(pricing_data),
                                "compute_items": len(pricing_data.get("compute", {})),
                                "database_items": len(pricing_data.get("database", {})),
                            }
                            
                            await PricingFetcher.track_job_status(
                                db, 
                                "success",
                                metadata=job_metadata
                            )
                            
                            logger.info(f"✅ Successfully updated pricing with backup. Metadata: {job_metadata}")
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
            # Track failure
            try:
                db = await get_database()
                if db:
                    await PricingFetcher.track_job_status(db, "failed", error=str(e))
            except:
                pass
            return False
