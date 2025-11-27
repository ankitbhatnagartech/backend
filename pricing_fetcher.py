import httpx
import json
import logging
import os
from datetime import datetime
from database import get_database

logger = logging.getLogger(__name__)

class PricingFetcher:
    # Azure Retail Prices API (Public)
    AZURE_API_URL = "https://prices.azure.com/api/retail/prices"
    
    # Vantage Public Pricing API (AWS)
    AWS_API_URL = "https://www.ec2instances.info/instances.json"

    @staticmethod
    async def fetch_aws_prices(client):
        """Fetch AWS pricing from Vantage public JSON"""
        try:
            logger.info("Fetching AWS prices from Vantage...")
            # This file is large, so we might want to stream it or just fetch specific regions if possible.
            # For MVP, we'll fetch it and filter in memory (it's around 10MB).
            response = await client.get(PricingFetcher.AWS_API_URL)
            data = response.json()
            
            # Find t3.medium in us-east-1
            for instance in data:
                if instance['instance_type'] == 't3.medium':
                    # pricing is a dict of region -> os -> price
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
            response = await client.get(f"{PricingFetcher.AZURE_API_URL}?$filter={query}")
            data = response.json()
            if data['Items']:
                return float(data['Items'][0]['retailPrice'])
            return None
        except Exception as e:
            logger.error(f"Error fetching Azure prices: {e}")
            return None

    @staticmethod
    async def fetch_gcp_prices(client):
        """Fetch GCP pricing (Simulated/Placeholder)"""
        # GCP Billing API requires auth. For MVP, we simulate or use a fixed multiplier.
        # In a real app, we'd use google-cloud-billing library.
        return 0.045 # Simulated e2-medium hourly

    @staticmethod
    async def fetch_do_prices(client):
        """Fetch DigitalOcean pricing (Simulated/Placeholder)"""
        # DO API requires auth.
        return 0.02 # Simulated Basic Droplet hourly

    async def fetch_currency_rates(client):
        """Fetch real-time currency exchange rates from ExchangeRate-API"""
        try:
            logger.info("Fetching currency exchange rates...")
            # Using ExchangeRate-API free tier (no auth needed)
            # Endpoint: https://api.exchangerate-api.com/v4/latest/USD
            response = await client.get("https://api.exchangerate-api.com/v4/latest/USD")
            data = response.json()
            
            if data and 'rates' in data:
                rates = data['rates']
                # Extract all currencies we support (55+ currencies)
                supported_currencies = [
                    # Americas
                    "USD", "CAD", "MXN", "BRL", "ARS", "CLP", "COP", "PEN",
                    # Europe
                    "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", 
                    "HUF", "RON", "BGN", "HRK", "TRY", "RUB",
                    # Asia-Pacific
                    "INR", "JPY", "CNY", "KRW", "SGD", "HKD", "TWD", "THB", 
                    "MYR", "IDR", "PHP", "VND", "PKR", "BDT", "LKR", "AUD", "NZD",
                    # Middle East & Africa
                    "AED", "SAR", "QAR", "KWD", "BHD", "ILS", "EGP", "ZAR", "NGN", "KES"
                ]
                
                currency_rates = {"USD": 1.0}  # Base currency
                for currency in supported_currencies:
                    if currency != "USD" and currency in rates:
                        currency_rates[currency] = rates[currency]
                
                logger.info(f"Fetched {len(currency_rates)} currency rates from API")
                return currency_rates
            return None
        except Exception as e:
            logger.error(f"Error fetching currency rates: {e}")
            return None

    @staticmethod
    async def fetch_latest_prices():
        """
        Fetches latest prices from all providers and updates MongoDB.
        """
        logger.info("Starting scheduled multi-cloud price fetch...")
        
        try:
            async with httpx.AsyncClient() as client:
                aws_price = await PricingFetcher.fetch_aws_prices(client)
                azure_price = await PricingFetcher.fetch_azure_prices(client)
                gcp_price = await PricingFetcher.fetch_gcp_prices(client)
                do_price = await PricingFetcher.fetch_do_prices(client)
                currency_rates = await PricingFetcher.fetch_currency_rates(client)
                
                # Baseline: AWS t3.medium (or fallback)
                baseline_hourly = aws_price if aws_price else 0.0416
                
                # Default currency rates if fetch failed
                if not currency_rates:
                    currency_rates = {
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
                
                # Calculate monthly costs (730 hours)
                pricing_data = {
                    "compute": {
                        "t3.micro": baseline_hourly * 0.25 * 730,
                        "t3.medium": baseline_hourly * 730,
                        "t3.large": baseline_hourly * 2 * 730,
                        "lambda_1m_requests": 0.20,
                        "fargate_vcpu": baseline_hourly * 0.9 * 730
                    },
                    "database": {
                        "rds_db.t3.micro": baseline_hourly * 0.3 * 730, # Approx
                        "rds_db.t3.medium": baseline_hourly * 1.5 * 730,
                        "dynamodb_unit": 0.25
                    },
                    "storage": {
                        "s3_gb": 0.023,
                        "ebs_gb": 0.10
                    },
                    "networking": {
                        "load_balancer": 16.20,
                        "data_transfer_gb": 0.09
                    },
                    "multi_cloud": {
                        "AWS": 1.0,
                        "Azure": (azure_price / baseline_hourly) if azure_price and baseline_hourly else 1.05,
                        "GCP": (gcp_price / baseline_hourly) if gcp_price and baseline_hourly else 0.95,
                        "DigitalOcean": (do_price / baseline_hourly) if do_price and baseline_hourly else 0.60,
                        "Vercel": 1.20 # Premium for managed experience
                    },
                    "currency_rates": currency_rates,
                    "meta": {
                        "last_updated": datetime.now().isoformat(),
                        "sources": ["Vantage (AWS)", "Azure Retail API", "ExchangeRate-API", "Simulated (GCP/DO)"]
                    }
                }

                # Save to MongoDB
                db = await get_database()
                if db is not None:
                    await db.pricing.update_one(
                        {"_id": "latest_pricing"},
                        {"$set": pricing_data},
                        upsert=True
                    )
                    logger.info("Successfully updated pricing in MongoDB")
                    return True
                else:
                    logger.error("Database connection not available")
                    return False
                
        except Exception as e:
            logger.error(f"Failed to fetch cloud prices: {str(e)}")
            return False
