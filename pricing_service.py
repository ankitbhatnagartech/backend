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
            "rds_db.t3.micro": 12.0, # Instance + Storage
            "rds_db.t3.medium": 60.0, # ~$0.082/hr
            "dynamodb_unit": 0.25 # WCU/RCU blended estimate
        },
        "storage": {
            "s3_gb": 0.023,
            "ebs_gb": 0.10
        },
        "networking": {
            "load_balancer": 16.20, # ALB minimum ~$0.0225/hr
            "data_transfer_gb": 0.09
        }
    }

    @classmethod
    async def load_dynamic_prices(cls):
        """Loads pricing from MongoDB if available."""
        from database import get_database
        
        try:
            db = await get_database()
            if db is not None:
                data = await db.pricing.find_one({"_id": "latest_pricing"})
                if data:
                    # Update PRICING dict with loaded data
                    for category, items in data.items():
                        if category in cls.PRICING and isinstance(items, dict):
                            cls.PRICING[category].update(items)
                        elif category == "multi_cloud":
                            cls.CLOUD_MULTIPLIERS.update(items)
                        elif category == "currency_rates":
                            cls.CURRENCY_RATES.update(items)
                            
                    logger.info(f"Loaded dynamic pricing from MongoDB (Source: {data.get('meta', {}).get('sources')})")
                else:
                    logger.info("No pricing data found in MongoDB, using defaults.")
            else:
                logger.warning("Database not available, using defaults.")
        except Exception as e:
            logger.error(f"Failed to load dynamic pricing from DB: {e}")

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

    # Multipliers relative to AWS (Simplified for MVP)
    CLOUD_MULTIPLIERS = {
        "AWS": 1.0,
        "Azure": 1.05, # Slightly more expensive generally
        "GCP": 0.95,   # Sustained use discounts often make it cheaper
        "DigitalOcean": 0.60, # Much cheaper for compute/bandwidth
        "Vercel": 1.20 # Premium for managed experience (Frontend/Serverless)
    }

    @staticmethod
    def get_price(category: str, item: str) -> float:
        return PricingService.PRICING.get(category, {}).get(item, 0.0)

    @staticmethod
    def convert(amount_usd: float, target_currency: str) -> float:
        rate = PricingService.CURRENCY_RATES.get(target_currency.upper(), 1.0)
        return amount_usd * rate
