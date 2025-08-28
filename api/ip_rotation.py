#!/usr/bin/env python3
"""
IP Rotation Service for BartoloVPN
Manages multiple endpoints and rotates IPs to avoid detection
"""

import asyncio
import aiohttp
import random
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database import ServerEndpoint, IPRotation, AsyncSessionLocal
from config import settings

class IPRotationService:
    """Service for managing IP rotation and endpoint selection"""
    
    def __init__(self):
        self.current_endpoints: Dict[str, ServerEndpoint] = {}
        self.rotation_tasks: Dict[int, asyncio.Task] = {}
        self.geoip_cache: Dict[str, Dict] = {}
        self.cache_expiry = 3600  # 1 hour
    
    async def initialize(self):
        """Initialize the IP rotation service"""
        await self.load_endpoints()
        await self.start_rotation_tasks()
        print("IP Rotation Service initialized")
    
    async def load_endpoints(self):
        """Load all active endpoints from database"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ServerEndpoint).where(ServerEndpoint.is_active == True)
            )
            endpoints = result.scalars().all()
            
            for endpoint in endpoints:
                self.current_endpoints[f"{endpoint.protocol}_{endpoint.id}"] = endpoint
    
    async def get_best_endpoint(self, protocol: str, user_country: Optional[str] = None) -> Optional[ServerEndpoint]:
        """Get the best endpoint for a given protocol and user location"""
        available_endpoints = [
            endpoint for key, endpoint in self.current_endpoints.items()
            if endpoint.protocol == protocol and endpoint.is_active
        ]
        
        if not available_endpoints:
            return None
        
        # Score endpoints based on various factors
        scored_endpoints = []
        for endpoint in available_endpoints:
            score = await self._calculate_endpoint_score(endpoint, user_country)
            scored_endpoints.append((endpoint, score))
        
        # Sort by score (higher is better) and return the best
        scored_endpoints.sort(key=lambda x: x[1], reverse=True)
        return scored_endpoints[0][0] if scored_endpoints else None
    
    async def _calculate_endpoint_score(self, endpoint: ServerEndpoint, user_country: Optional[str] = None) -> float:
        """Calculate a score for an endpoint based on various factors"""
        score = 0.0
        
        # Priority score (lower number = higher priority)
        score += (10 - endpoint.priority) * 10
        
        # Usage count (prefer less used endpoints)
        score += max(0, 100 - endpoint.usage_count)
        
        # Geographic proximity (if user country is known)
        if user_country and endpoint.country:
            if user_country == endpoint.country:
                score += 50  # Same country bonus
            else:
                # Add some score based on geographic proximity
                score += 20
        
        # Recent usage penalty
        if endpoint.last_used:
            time_since_last_use = (datetime.utcnow() - endpoint.last_used).total_seconds()
            if time_since_last_use < 300:  # 5 minutes
                score -= 30  # Penalty for recently used endpoints
        
        # Random factor to avoid predictable patterns
        score += random.uniform(-10, 10)
        
        return score
    
    async def rotate_endpoint(self, endpoint_id: int):
        """Rotate a specific endpoint to a new IP"""
        async with AsyncSessionLocal() as session:
            endpoint = await session.get(ServerEndpoint, endpoint_id)
            if not endpoint:
                return False
            
            # Get new IP from rotation service
            new_ip = await self._get_new_ip_for_endpoint(endpoint)
            if new_ip:
                endpoint.ip_address = new_ip
                endpoint.last_used = datetime.utcnow()
                await session.commit()
                
                # Update cache
                cache_key = f"{endpoint.protocol}_{endpoint.id}"
                self.current_endpoints[cache_key] = endpoint
                
                print(f"Rotated endpoint {endpoint.name} to new IP: {new_ip}")
                return True
        
        return False
    
    async def _get_new_ip_for_endpoint(self, endpoint: ServerEndpoint) -> Optional[str]:
        """Get a new IP address for an endpoint"""
        # This is where you would integrate with your IP rotation provider
        # Examples: AWS, DigitalOcean, Linode, etc.
        
        # For now, we'll simulate IP rotation with a simple algorithm
        # In production, you would:
        # 1. Call your cloud provider's API
        # 2. Create a new instance/endpoint
        # 3. Update DNS records
        # 4. Wait for propagation
        
        current_ip = endpoint.ip_address
        
        # Simple simulation - in reality, this would be a cloud API call
        if current_ip == "your-server-ip":
            # Simulate getting a new IP
            new_ip = f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}"
            return new_ip
        
        return None
    
    async def start_rotation_tasks(self):
        """Start background tasks for automatic IP rotation"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(IPRotation).where(IPRotation.is_enabled == True)
            )
            rotations = result.scalars().all()
            
            for rotation in rotations:
                task = asyncio.create_task(self._rotation_task(rotation))
                self.rotation_tasks[rotation.id] = task
    
    async def _rotation_task(self, rotation: IPRotation):
        """Background task for automatic IP rotation"""
        while True:
            try:
                # Check if it's time to rotate
                if rotation.next_rotation and datetime.utcnow() >= rotation.next_rotation:
                    await self.rotate_endpoint(rotation.endpoint_id)
                    
                    # Update next rotation time
                    async with AsyncSessionLocal() as session:
                        rotation.last_rotation = datetime.utcnow()
                        rotation.next_rotation = datetime.utcnow() + timedelta(seconds=rotation.rotation_interval)
                        await session.commit()
                
                # Sleep for a minute before checking again
                await asyncio.sleep(60)
                
            except Exception as e:
                print(f"Error in rotation task: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retrying
    
    async def get_geoip_info(self, ip_address: str) -> Dict[str, Any]:
        """Get geographic information for an IP address"""
        # Check cache first
        if ip_address in self.geoip_cache:
            cache_entry = self.geoip_cache[ip_address]
            if datetime.utcnow().timestamp() - cache_entry['timestamp'] < self.cache_expiry:
                return cache_entry['data']
        
        try:
            # Use a free GeoIP service (in production, use a paid service)
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://ip-api.com/json/{ip_address}") as response:
                    if response.status == 200:
                        data = await response.json()
                        geoip_data = {
                            'country': data.get('countryCode'),
                            'country_name': data.get('country'),
                            'region': data.get('regionName'),
                            'city': data.get('city'),
                            'isp': data.get('isp'),
                            'timezone': data.get('timezone')
                        }
                        
                        # Cache the result
                        self.geoip_cache[ip_address] = {
                            'data': geoip_data,
                            'timestamp': datetime.utcnow().timestamp()
                        }
                        
                        return geoip_data
        except Exception as e:
            print(f"Error getting GeoIP info: {e}")
        
        return {'country': 'Unknown', 'country_name': 'Unknown'}
    
    async def add_endpoint(self, name: str, ip_address: str, port: int, protocol: str, country: str = None, priority: int = 1) -> ServerEndpoint:
        """Add a new endpoint"""
        async with AsyncSessionLocal() as session:
            endpoint = ServerEndpoint(
                name=name,
                ip_address=ip_address,
                port=port,
                protocol=protocol,
                country=country,
                priority=priority,
                is_active=True
            )
            session.add(endpoint)
            await session.commit()
            await session.refresh(endpoint)
            
            # Update cache
            cache_key = f"{protocol}_{endpoint.id}"
            self.current_endpoints[cache_key] = endpoint
            
            return endpoint
    
    async def remove_endpoint(self, endpoint_id: int) -> bool:
        """Remove an endpoint"""
        async with AsyncSessionLocal() as session:
            endpoint = await session.get(ServerEndpoint, endpoint_id)
            if not endpoint:
                return False
            
            endpoint.is_active = False
            await session.commit()
            
            # Remove from cache
            cache_key = f"{endpoint.protocol}_{endpoint.id}"
            if cache_key in self.current_endpoints:
                del self.current_endpoints[cache_key]
            
            return True
    
    async def get_endpoint_stats(self) -> Dict[str, Any]:
        """Get statistics about all endpoints"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(ServerEndpoint))
            endpoints = result.scalars().all()
            
            stats = {
                'total_endpoints': len(endpoints),
                'active_endpoints': len([e for e in endpoints if e.is_active]),
                'by_protocol': {},
                'by_country': {},
                'recent_usage': []
            }
            
            for endpoint in endpoints:
                # Protocol stats
                if endpoint.protocol not in stats['by_protocol']:
                    stats['by_protocol'][endpoint.protocol] = 0
                stats['by_protocol'][endpoint.protocol] += 1
                
                # Country stats
                if endpoint.country:
                    if endpoint.country not in stats['by_country']:
                        stats['by_country'][endpoint.country] = 0
                    stats['by_country'][endpoint.country] += 1
                
                # Recent usage
                if endpoint.last_used:
                    stats['recent_usage'].append({
                        'name': endpoint.name,
                        'protocol': endpoint.protocol,
                        'last_used': endpoint.last_used.isoformat(),
                        'usage_count': endpoint.usage_count
                    })
            
            # Sort recent usage by last_used
            stats['recent_usage'].sort(key=lambda x: x['last_used'], reverse=True)
            
            return stats

# Global instance
ip_rotation_service = IPRotationService()
