"""
Rate limiting middleware using slowapi
"""
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Create limiter instance
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# Rate limit configurations
RATE_LIMITS = {
    "estimate": "20/minute",  # Cost estimation endpoint
    "providers": "60/minute",  # Provider list endpoint  
    "pricing_status": "60/minute",  # Pricing status endpoint
    "admin": "10/minute",  # Admin endpoints
}

def get_rate_limiter():
    """Get the rate limiter instance"""
    return limiter
