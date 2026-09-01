# erp_adapters.py
#
# ERP system adapter implementations for material master synchronization.
# Supports SAP MM, Oracle, and generic HTTP-based ERP systems.
#
# Each adapter implements the ERPAdapter interface and can:
# - Transmit standardized material data to the ERP system
# - Handle authentication and error scenarios
# - Track job status and provide acknowledgements
# - Support retry logic with exponential backoff

import os
import json
import requests
import time
import logging
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class ERPAdapter(ABC):
    """Abstract base class for ERP system adapters."""
    
    def __init__(self, config: Dict):
        """Initialize adapter with configuration.
        
        Args:
            config: Dict with adapter-specific settings (endpoint, credentials, etc.)
        """
        self.config = config
        self.timeout = config.get('timeout', 30)
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 1)
    
    @abstractmethod
    def transmit(self, payload: List[Dict], job_id: str) -> Tuple[bool, str]:
        """Send material data to ERP system.
        
        Args:
            payload: List of material records to send
            job_id: Unique job identifier for tracking
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        pass
    
    def _retry_with_backoff(self, func, max_attempts: int = None):
        """Execute function with exponential backoff retry logic.
        
        Args:
            func: Callable to execute
            max_attempts: Max retry attempts (uses self.max_retries if None)
        
        Returns:
            Result of func() if successful, raises exception otherwise
        """
        max_attempts = max_attempts or self.max_retries
        delay = self.retry_delay
        
        for attempt in range(max_attempts):
            try:
                return func()
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff


class SAPMMAdapter(ERPAdapter):
    """SAP Material Master (MM) module adapter.
    
    Integrates with SAP MM via OData V4 API.
    Maps to MARA (General Data), MARC (Plant-specific), MAKT (Descriptions).
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.sap_endpoint = config.get('sap_endpoint', 'http://localhost:8080/sap/opu/odata/sap')
        self.sap_user = config.get('sap_user')
        self.sap_password = config.get('sap_password')
        self.sap_client = config.get('sap_client', '100')
        
        if not all([self.sap_user, self.sap_password]):
            raise ValueError("SAP credentials (sap_user, sap_password) required in config")
    
    def transmit(self, payload: List[Dict], job_id: str) -> Tuple[bool, str]:
        """Send materials to SAP MM system.
        
        Args:
            payload: List of standardized material records
            job_id: Job tracking ID
        
        Returns:
            (success, message_string)
        """
        successful = 0
        failed = 0
        errors = []
        
        for idx, item in enumerate(payload, start=1):
            try:
                success = self._transmit_material(item)
                if success:
                    successful += 1
                else:
                    failed += 1
                    errors.append(f"Row {idx}: {item.get('common_code')} - transmission failed")
            except Exception as e:
                failed += 1
                errors.append(f"Row {idx}: {item.get('common_code')} - {str(e)}")
                logger.error(f"Error transmitting material {item.get('common_code')}: {e}")
        
        message = f"SAP Transmission: {successful} success, {failed} failed"
        if errors:
            message += f". Errors: {'; '.join(errors[:5])}"
        
        success = failed == 0
        return (success, message)
    
    def _transmit_material(self, material: Dict) -> bool:
        """Transmit a single material to SAP via OData API."""
        
        def _send():
            # Prepare MARA (general material data)
            mara_data = {
                'MATNR': material.get('common_code'),  # Material number
                'MAKTX': material.get('description', '')[:40],  # Description
                'MEINS': material.get('unit_of_measure', 'EA'),  # Base UoM
                'MTART': self._map_category_to_sap_type(material.get('category')),  # Material type
                'MFRPN': material.get('common_code'),  # Manufacturer part number
            }
            
            # Send to SAP
            url = urljoin(self.sap_endpoint, '/C_MATERIALHEADER/0')
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'x-csrf-token': self._get_sap_csrf_token(),
            }
            
            response = requests.post(
                url,
                auth=(self.sap_user, self.sap_password),
                json=mara_data,
                headers=headers,
                timeout=self.timeout,
                verify=False  # TODO: Use proper SSL verification in production
            )
            
            if not response.ok:
                logger.error(f"SAP API error: {response.status_code} - {response.text}")
                return False
            
            logger.info(f"Successfully transmitted {material.get('common_code')} to SAP")
            return True
        
        return self._retry_with_backoff(_send)
    
    def _get_sap_csrf_token(self) -> str:
        """Fetch CSRF token from SAP for security."""
        try:
            response = requests.get(
                urljoin(self.sap_endpoint, '/C_MATERIALHEADER'),
                auth=(self.sap_user, self.sap_password),
                headers={'x-csrf-token': 'fetch'},
                timeout=self.timeout,
                verify=False
            )
            return response.headers.get('x-csrf-token', '')
        except Exception as e:
            logger.warning(f"Could not fetch CSRF token: {e}")
            return ''
    
    def _map_category_to_sap_type(self, category: str) -> str:
        """Map application category to SAP material type code.
        
        SAP uses standard type codes like:
        - FERT: Finished goods
        - HALB: Semi-finished goods
        - ROH: Raw materials
        - HAWA: Trading goods
        """
        mapping = {
            'Pipe': 'HALB',
            'Valve': 'HAWA',
            'Fastener': 'HAWA',
            'Electrical Cable': 'HAWA',
            'Electrical Switchgear': 'HAWA',
            'Plate': 'HALB',
            'Bearing': 'HAWA',
            'Motor': 'FERT',
            'Pump': 'FERT',
            'Chemical': 'ROH',
            'Lubricant': 'HAWA',
            'Gasket / Seal': 'HAWA',
            'Instrument': 'HAWA',
            'Structural Steel': 'HALB',
            'Paint / Coating': 'HAWA',
            'Safety Equipment': 'HAWA',
            'Tool': 'HAWA',
        }
        return mapping.get(category, 'HAWA')


class OracleInvAdapter(ERPAdapter):
    """Oracle Inventory (INV) module adapter.
    
    Integrates with Oracle Inventory via REST API.
    Maps to MTL_SYSTEM_ITEMS_B and MTL_ITEM_REVISIONS tables.
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.oracle_endpoint = config.get('oracle_endpoint', 'http://localhost:8000/api')
        self.oracle_user = config.get('oracle_user')
        self.oracle_password = config.get('oracle_password')
        self.organization_id = config.get('organization_id', '1')
        
        if not all([self.oracle_user, self.oracle_password]):
            raise ValueError("Oracle credentials required in config")
    
    def transmit(self, payload: List[Dict], job_id: str) -> Tuple[bool, str]:
        """Send materials to Oracle Inventory system."""
        successful = 0
        failed = 0
        errors = []
        
        for idx, item in enumerate(payload, start=1):
            try:
                success = self._transmit_material(item)
                if success:
                    successful += 1
                else:
                    failed += 1
                    errors.append(f"Row {idx}: {item.get('common_code')}")
            except Exception as e:
                failed += 1
                errors.append(f"Row {idx}: {str(e)}")
                logger.error(f"Oracle transmission error: {e}")
        
        message = f"Oracle: {successful} success, {failed} failed"
        if errors:
            message += f" ({len(errors)} items)"
        
        return (failed == 0, message)
    
    def _transmit_material(self, material: Dict) -> bool:
        """Transmit a single material to Oracle via REST API."""
        
        def _send():
            item_data = {
                'item_code': material.get('common_code'),
                'item_description': material.get('description', ''),
                'organization_id': self.organization_id,
                'unit_of_measure': material.get('unit_of_measure', 'EA'),
                'item_type': self._map_category_to_oracle_type(material.get('category')),
                'category': material.get('category', 'Miscellaneous'),
                'attributes': material.get('attributes', {}),
            }
            
            url = f"{self.oracle_endpoint}/inventory/items"
            response = requests.post(
                url,
                auth=(self.oracle_user, self.oracle_password),
                json=item_data,
                timeout=self.timeout
            )
            
            if not response.ok:
                logger.error(f"Oracle API error: {response.status_code} - {response.text}")
                return False
            
            logger.info(f"Successfully transmitted {material.get('common_code')} to Oracle")
            return True
        
        return self._retry_with_backoff(_send)
    
    def _map_category_to_oracle_type(self, category: str) -> str:
        """Map category to Oracle item type."""
        return category if category else 'Miscellaneous'


class GenericHTTPAdapter(ERPAdapter):
    """Generic HTTP-based ERP adapter for REST API systems.
    
    Works with any ERP system that exposes a REST API for material creation.
    Supports custom field mapping via configuration.
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.api_endpoint = config.get('api_endpoint')
        self.api_key = config.get('api_key')
        self.api_key_header = config.get('api_key_header', 'X-API-Key')
        self.field_mapping = config.get('field_mapping', {})
        
        if not self.api_endpoint:
            raise ValueError("api_endpoint required in config")
    
    def transmit(self, payload: List[Dict], job_id: str) -> Tuple[bool, str]:
        """Send materials to generic HTTP ERP endpoint."""
        successful = 0
        failed = 0
        errors = []
        
        for idx, item in enumerate(payload, start=1):
            try:
                success = self._transmit_material(item)
                if success:
                    successful += 1
                else:
                    failed += 1
                    errors.append(f"Row {idx}")
            except Exception as e:
                failed += 1
                errors.append(f"Row {idx}: {str(e)[:50]}")
        
        message = f"HTTP API: {successful} success, {failed} failed (Job: {job_id})"
        return (failed == 0, message)
    
    def _transmit_material(self, material: Dict) -> bool:
        """Send material to HTTP endpoint."""
        
        def _send():
            # Apply field mapping if configured
            payload = self._apply_field_mapping(material)
            
            headers = {'Content-Type': 'application/json'}
            if self.api_key:
                headers[self.api_key_header] = self.api_key
            
            response = requests.post(
                self.api_endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            if not response.ok:
                logger.error(f"HTTP API error: {response.status_code}")
                return False
            
            logger.info(f"Transmitted {material.get('common_code')} via HTTP")
            return True
        
        return self._retry_with_backoff(_send)
    
    def _apply_field_mapping(self, material: Dict) -> Dict:
        """Apply custom field mapping from config."""
        if not self.field_mapping:
            return material  # Use as-is if no mapping
        
        mapped = {}
        for source_field, target_field in self.field_mapping.items():
            if source_field in material:
                mapped[target_field] = material[source_field]
        
        # Fallback: include unmapped fields with underscore prefix
        for field, value in material.items():
            if field not in mapped:
                mapped[f"_{field}"] = value
        
        return mapped


class SimulatedAdapter(ERPAdapter):
    """Simulated ERP adapter for testing without real ERP system.
    
    Useful for demos, testing, and development.
    Simulates successful transmission with configurable latency.
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.simulate_latency = config.get('simulate_latency', 0.1)
        self.failure_rate = config.get('failure_rate', 0.0)  # Percentage
    
    def transmit(self, payload: List[Dict], job_id: str) -> Tuple[bool, str]:
        """Simulate transmission."""
        import random
        
        successful = 0
        failed = 0
        
        for item in payload:
            time.sleep(self.simulate_latency)
            
            # Simulate random failures if configured
            if random.random() < self.failure_rate:
                failed += 1
            else:
                successful += 1
            
            logger.info(f"[SIMULATED] {item.get('common_code')} transmitted")
        
        message = f"SIMULATED: {successful} success, {failed} failed"
        return (failed == 0, message)


# Registry of available adapters
ADAPTERS = {
    'sap': SAPMMAdapter,
    'sap-mm': SAPMMAdapter,
    'oracle': OracleInvAdapter,
    'oracle-inv': OracleInvAdapter,
    'http': GenericHTTPAdapter,
    'generic': GenericHTTPAdapter,
    'simulated': SimulatedAdapter,
    'demo': SimulatedAdapter,
}


def get_adapter(adapter_name: str, config: Dict) -> Optional[ERPAdapter]:
    """Factory function to create adapter instance.
    
    Args:
        adapter_name: Name of adapter (e.g., 'sap', 'oracle', 'http')
        config: Configuration dictionary for adapter
    
    Returns:
        Adapter instance or None if adapter not found
    """
    adapter_class = ADAPTERS.get(adapter_name.lower())
    if not adapter_class:
        logger.error(f"Adapter '{adapter_name}' not found. Available: {list(ADAPTERS.keys())}")
        return None
    
    try:
        return adapter_class(config)
    except Exception as e:
        logger.error(f"Failed to initialize {adapter_name} adapter: {e}")
        return None


def load_adapter_config(adapter_name: str) -> Dict:
    """Load adapter configuration from environment variables.
    
    Looks for env vars like:
    - ADAPTER_<ADAPTER_NAME>_<SETTING> (e.g., ADAPTER_SAP_ENDPOINT)
    - ERP_<SETTING> (fallback)
    
    Returns:
        Configuration dictionary
    """
    config = {}
    prefix = f"ADAPTER_{adapter_name.upper()}_"
    
    for key, value in os.environ.items():
        if key.startswith(prefix):
            config_key = key[len(prefix):].lower()
            config[config_key] = value
    
    # Fallback to ERP_* env vars
    for key, value in os.environ.items():
        if key.startswith("ERP_") and key[4:].lower() not in config:
            config[key[4:].lower()] = value
    
    return config
