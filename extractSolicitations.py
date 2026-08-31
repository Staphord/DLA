from django.conf import settings
import random
import ssl
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    WebDriverException, NoSuchWindowException, TimeoutException)
import MySQLdb
from MySQLdb.cursors import DictCursor
import json
import requests
import os
import sys
import django
import datetime
import pdfplumber
import io
import re
import time
from bs4 import BeautifulSoup
import urllib3
import traceback
from urllib3.exceptions import MaxRetryError
import tempfile
import contextlib
from collections import defaultdict
import concurrent.futures
import threading
import asyncio
import aiohttp
import gc
from functools import lru_cache
import pickle

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set up Django environment FIRST (before importing GPT-4 extractor which needs settings)
# Add project to Python path (dynamic - use script's directory)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir) if os.path.basename(script_dir) != 'DLA-NEW' else script_dir
sys.path.append(project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RFQ.settings')
django.setup()

# Import GPT-4 PDF extractor (optional - only if AI extraction is needed)
# Must be imported AFTER Django setup because it accesses Django settings
try:
    from gpt4_pdf_extractor import extract_pdf_fields_with_gpt4
    GPT4_PDF_EXTRACTION_AVAILABLE = True
    print("GPT-4 PDF extractor loaded successfully")
except (ImportError, ValueError, Exception) as e:
    GPT4_PDF_EXTRACTION_AVAILABLE = False
    print(f"Warning: GPT-4 PDF extractor not available: {e}")
    print("AI extraction will be skipped.")

# Variables from Django settings
DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASSWORD = 'ndalami0213'
DB_NAME = 'rfqnew'
DB_PORT = 3306

# OPTIMIZED Chrome options for maximum performance - FIXED GPU ISSUES


def get_optimized_chrome_options():
    chrome_options = Options()

    # Essential performance optimizations
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # ENHANCED: More complete GPU disabling
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-gpu-compositing")
    chrome_options.add_argument("--disable-gpu-rasterization")
    chrome_options.add_argument("--disable-gpu-sandbox")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-accelerated-2d-canvas")
    chrome_options.add_argument("--disable-accelerated-jpeg-decoding")
    chrome_options.add_argument("--disable-accelerated-mjpeg-decode")
    chrome_options.add_argument("--disable-accelerated-video-decode")
    chrome_options.add_argument("--disable-accelerated-video-encode")
    chrome_options.add_argument("--disable-webgl")
    chrome_options.add_argument("--disable-webgl2")
    chrome_options.add_argument("--disable-3d-apis")
    chrome_options.add_argument("--use-gl=disabled")
    chrome_options.add_argument(
        "--disable-features=VizDisplayCompositor,VizHitTestSurfaceLayer")

    # Memory optimizations
    chrome_options.add_argument("--memory-pressure-off")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-renderer-backgrounding")

    # Disable unnecessary features for speed
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--disable-web-security")

    # SSL and security
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--allow-running-insecure-content')
    chrome_options.add_argument('--allow-insecure-localhost')
    chrome_options.add_argument(
        "--disable-blink-features=AutomationControlled")

    # Network optimizations
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-default-apps")
    chrome_options.add_argument("--disable-sync")

    # Optional WARP SOCKS5 proxy configuration
    if USE_WARP_PROXY:
        chrome_options.add_argument("--proxy-server=socks5://127.0.0.1:40000")

    # Process management
    chrome_options.add_argument("--renderer-process-limit=1")

    # ENHANCED: Logging control
    chrome_options.add_argument("--log-level=3")  # Only fatal errors
    chrome_options.add_argument("--silent")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--disable-gpu-process-crash-limit")
    chrome_options.add_argument("--disable-crash-reporter")
    chrome_options.add_argument("--disable-in-process-stack-traces")

    # DevTools suppression (WORKING!)
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--remote-debugging-port=0")

    return chrome_options


# Create custom SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Apply to requests
requests.packages.urllib3.disable_warnings()
requests.adapters.DEFAULT_RETRIES = 3

print("STARTING OPTIMIZED SCRIPT WITH COMPLETE DATA EXTRACTION---------------------------------")

# Cloudflare WARP proxy
USE_WARP_PROXY = True
WARP_PROXIES = {
    "http": "socks5h://127.0.0.1:40000",
    "https": "socks5h://127.0.0.1:40000",
}

# Create a persistent session for connection pooling
_warp_session = None
_warp_session_lock = threading.Lock()
_warp_session_failures = 0
MAX_SESSION_FAILURES = 5

def reset_warp_session():
    """Reset the WARP session to clear connection pool issues"""
    global _warp_session, _warp_session_failures
    with _warp_session_lock:
        if _warp_session is not None:
            try:
                _warp_session.close()
            except:
                pass
        _warp_session = None
        _warp_session_failures = 0
        print("[WARP] Session reset")

def get_warp_session():
    """Get or create a persistent WARP session with connection pooling"""
    global _warp_session, _warp_session_failures
    if _warp_session is None or _warp_session_failures >= MAX_SESSION_FAILURES:
        with _warp_session_lock:
            if _warp_session is None or _warp_session_failures >= MAX_SESSION_FAILURES:
                if _warp_session is not None:
                    try:
                        _warp_session.close()
                    except:
                        pass
                
                from requests.adapters import HTTPAdapter
                from urllib3.util.retry import Retry
                
                _warp_session = requests.Session()
                _warp_session.proxies = WARP_PROXIES
                
                # Configure retry strategy - more conservative to avoid overwhelming proxy
                retry_strategy = Retry(
                    total=2,  # Reduced from 3 to avoid too many retries
                    backoff_factor=0.5,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "HEAD"],
                    raise_on_status=False
                )
                
                # Use HTTPAdapter with connection pooling - smaller pools to avoid exhaustion
                adapter = HTTPAdapter(
                    max_retries=retry_strategy,
                    pool_connections=5,  # Reduced from 10
                    pool_maxsize=10,  # Reduced from 20
                    pool_block=False
                )
                _warp_session.mount("http://", adapter)
                _warp_session.mount("https://", adapter)
                
                # Set default timeout
                _warp_session.timeout = 45
                _warp_session_failures = 0
                print("[WARP] New session created")
    return _warp_session

def test_warp_connection():
    """Test if WARP proxy is working"""
    try:
        session = get_warp_session()
        # Quick test to a reliable endpoint
        response = session.get("https://www.google.com", timeout=10)
        if response.status_code == 200:
            return True
    except Exception as e:
        print(f"[WARP] Connection test failed: {e}")
        return False
    return False

def warp_get(url, max_retries=3, **kwargs):
    """Perform HTTP GET through WARP SOCKS5 proxy with improved error handling"""
    global _warp_session_failures

    if not USE_WARP_PROXY:
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 45
        kwargs.pop('stream', None)

        for attempt in range(max_retries):
            try:
                response = requests.get(url, **kwargs)
                if response.status_code >= 500:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                        print(f"[DIRECT GET] HTTP {response.status_code} server error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time:.2f} seconds...")
                        time.sleep(wait_time)
                        continue
                    print(f"[DIRECT GET] HTTP {response.status_code} server error after {max_retries} attempts: {url[:100]}")
                    return None
                if response.status_code >= 400:
                    print(f"[DIRECT GET] HTTP {response.status_code} client error (not retrying): {url[:100]}")
                    return None
                return response
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                    print(f"[DIRECT GET] Request error (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}")
                    print(f"[DIRECT GET] Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                    continue
                print(f"[DIRECT GET] Error after {max_retries} attempts: {str(e)[:200]}")
                return None
    
    session = get_warp_session()
    
    # Default timeout if not provided
    if 'timeout' not in kwargs:
        kwargs['timeout'] = 45
    
    # Add small delay between requests to avoid overwhelming proxy
    time.sleep(0.1)
    
    # Retry logic with exponential backoff
    for attempt in range(max_retries):
        try:
            response = session.get(url, **kwargs)
            # Check status code directly - handle 5xx errors with retry, 4xx errors without retry
            if response.status_code >= 500:
                # 5xx server errors - retry
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                    print(f"[WARP GET] HTTP {response.status_code} server error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"[WARP GET] HTTP {response.status_code} server error after {max_retries} attempts: {url[:100]}")
                    return None
            elif response.status_code >= 400:
                # 4xx client errors - don't retry
                print(f"[WARP GET] HTTP {response.status_code} client error (not retrying): {url[:100]}")
                return None
            
            # Success - reset failure counter
            if _warp_session_failures > 0:
                _warp_session_failures = max(0, _warp_session_failures - 1)
            return response
        except requests.exceptions.ProxyError as e:
            error_msg = str(e)
            _warp_session_failures += 1
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)  # Exponential backoff with jitter
                print(f"[WARP GET] Proxy error (attempt {attempt + 1}/{max_retries}): {error_msg[:100]}")
                print(f"[WARP GET] Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                # Reset session if too many failures
                if _warp_session_failures >= MAX_SESSION_FAILURES:
                    print("[WARP GET] Too many failures, resetting session...")
                    reset_warp_session()
                    session = get_warp_session()
                continue
            else:
                print(f"[WARP GET] Proxy error after {max_retries} attempts: {error_msg[:200]}")
                return None
        except requests.exceptions.ConnectionError as e:
            error_msg = str(e)
            _warp_session_failures += 1
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"[WARP GET] Connection error (attempt {attempt + 1}/{max_retries}): {error_msg[:100]}")
                print(f"[WARP GET] Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                # Reset session if too many failures
                if _warp_session_failures >= MAX_SESSION_FAILURES:
                    print("[WARP GET] Too many failures, resetting session...")
                    reset_warp_session()
                    session = get_warp_session()
                continue
            else:
                print(f"[WARP GET] Connection error after {max_retries} attempts: {error_msg[:200]}")
                return None
        except requests.exceptions.Timeout as e:
            _warp_session_failures += 1
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"[WARP GET] Timeout (attempt {attempt + 1}/{max_retries}), retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                continue
            else:
                print(f"[WARP GET] Timeout after {max_retries} attempts: {e}")
                return None
        except requests.exceptions.HTTPError as e:
            # For HTTP errors, retry on 5xx server errors
            status_code = None
            if e.response is not None:
                status_code = e.response.status_code
            
            if status_code and status_code >= 500 and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"[WARP GET] HTTP {status_code} server error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                continue
            elif status_code:
                print(f"[WARP GET] HTTP {status_code} error (not retrying): {e}")
                return None
            else:
                print(f"[WARP GET] HTTP error: {e}")
                return None
        except Exception as e:
            error_msg = str(e)
            _warp_session_failures += 1
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"[WARP GET] Unexpected error (attempt {attempt + 1}/{max_retries}): {error_msg[:100]}")
                print(f"[WARP GET] Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                continue
            else:
                print(f"[WARP GET] Error after {max_retries} attempts: {error_msg[:200]}")
                return None
    
    return None


# Global variables for hang detection
last_active = time.time()
TIMEOUT_THRESHOLD = 1800  # 30 minutes

# Progress tracking - use dynamic path based on script location
script_dir = os.path.dirname(os.path.abspath(__file__))
logs_dir = os.path.join(script_dir, 'logs')
os.makedirs(logs_dir, exist_ok=True)  # Create logs directory if it doesn't exist
PROGRESS_FILE = os.path.join(logs_dir, 'scrape_progress.json')

def update_progress(stage, current, total, message="", status="running"):
    """Update progress tracking file"""
    try:
        progress_data = {
            "stage": stage,  # "extracting", "processing_nsns", "completed"
            "current": current,
            "total": total,
            "percentage": int((current / total * 100)) if total > 0 else 0,
            "message": message,
            "status": status,  # "running", "completed", "failed"
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(progress_data, f)
    except Exception as e:
        print(f"Error updating progress: {e}")

def clear_progress():
    """Clear progress tracking file"""
    try:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print("Progress file cleared")
    except Exception as e:
        print(f"Error clearing progress file: {e}")

# ENHANCED CACHING SYSTEM WITH 180-DAY EXPIRATION
CACHE_DURATION_DAYS = 180  # 180 days cache duration
CACHE_FILE_PATH = 'cage_cache_90day.pkl'


def load_cage_cache():
    """Load CAGE cache from file with expiration checking"""
    if not os.path.exists(CACHE_FILE_PATH):
        print("No existing cache file found. Starting with empty cache.")
        return {}

    try:
        with open(CACHE_FILE_PATH, 'rb') as f:
            cached_data = pickle.load(f)

        # Check if cache structure is valid (has timestamps)
        if not isinstance(cached_data, dict):
            print("Invalid cache structure. Starting with empty cache.")
            return {}

        current_time = datetime.datetime.now()
        valid_cache = {}
        expired_count = 0

        for cage_code, cache_entry in cached_data.items():
            # Check if cache entry has timestamp (new format)
            if isinstance(cache_entry, dict) and 'timestamp' in cache_entry and 'data' in cache_entry:
                cache_timestamp = cache_entry['timestamp']
                days_since_cache = (current_time - cache_timestamp).days

                if days_since_cache < CACHE_DURATION_DAYS:
                    valid_cache[cage_code] = cache_entry['data']
                    # print(f"Cache valid for CAGE {cage_code}: {days_since_cache} days old")
                else:
                    expired_count += 1
                    print(
                        f"Cache expired for CAGE {cage_code}: {days_since_cache} days old")
            else:
                # Old cache format without timestamp - treat as expired
                expired_count += 1
                print(
                    f"Old cache format for CAGE {cage_code} - treating as expired")

        print(
            f"Loaded cache: {len(valid_cache)} valid entries, {expired_count} expired entries removed")
        return valid_cache

    except Exception as e:
        print(f"Error loading cache file: {e}")
        print("Starting with empty cache.")
        return {}


def save_cage_cache(cage_cache):
    """Save CAGE cache to file with timestamps"""
    try:
        current_time = datetime.datetime.now()

        # Load existing cache to preserve timestamps
        existing_cached_data = {}
        if os.path.exists(CACHE_FILE_PATH):
            try:
                with open(CACHE_FILE_PATH, 'rb') as f:
                    existing_cached_data = pickle.load(f)
            except:
                existing_cached_data = {}

        # Prepare cache data with timestamps
        cache_data_with_timestamps = {}

        for cage_code, cage_data in cage_cache.items():
            # Check if we already have this CAGE code with timestamp
            if (cage_code in existing_cached_data and
                isinstance(existing_cached_data[cage_code], dict) and
                    'timestamp' in existing_cached_data[cage_code]):
                # Keep existing timestamp if data hasn't changed
                existing_data = existing_cached_data[cage_code]['data']
                if existing_data == cage_data:
                    cache_data_with_timestamps[cage_code] = existing_cached_data[cage_code]
                else:
                    # Data changed, update with new timestamp
                    cache_data_with_timestamps[cage_code] = {
                        'timestamp': current_time,
                        'data': cage_data
                    }
            else:
                # New entry, add current timestamp
                cache_data_with_timestamps[cage_code] = {
                    'timestamp': current_time,
                    'data': cage_data
                }

        # Save to file
        with open(CACHE_FILE_PATH, 'wb') as f:
            pickle.dump(cache_data_with_timestamps, f)

        print(
            f"Cache saved successfully: {len(cache_data_with_timestamps)} entries")

        # Print cache statistics
        new_entries = sum(1 for entry in cache_data_with_timestamps.values()
                          if (current_time - entry['timestamp']).days == 0)
        print(
            f"Cache statistics: {new_entries} new entries added in this session")

    except Exception as e:
        print(f"Error saving cache file: {e}")


def get_cache_info():
    """Get information about current cache status"""
    if not os.path.exists(CACHE_FILE_PATH):
        return "No cache file exists"

    try:
        with open(CACHE_FILE_PATH, 'rb') as f:
            cached_data = pickle.load(f)

        if not isinstance(cached_data, dict):
            return "Invalid cache format"

        current_time = datetime.datetime.now()
        total_entries = len(cached_data)
        valid_entries = 0
        expired_entries = 0

        age_distribution = {
            '0-7 days': 0,
            '8-30 days': 0,
            '31-60 days': 0,
            '61-120 days': 0,
            '180+ days (expired)': 0
        }

        for cage_code, cache_entry in cached_data.items():
            if isinstance(cache_entry, dict) and 'timestamp' in cache_entry:
                days_old = (current_time - cache_entry['timestamp']).days

                if days_old < CACHE_DURATION_DAYS:
                    valid_entries += 1
                    if days_old <= 7:
                        age_distribution['0-7 days'] += 1
                    elif days_old <= 30:
                        age_distribution['8-30 days'] += 1
                    elif days_old <= 60:
                        age_distribution['31-60 days'] += 1
                    else:
                        age_distribution['61-120 days'] += 1
                else:
                    expired_entries += 1
                    age_distribution['180+ days (expired)'] += 1
            else:
                expired_entries += 1
                age_distribution['180+ days (expired)'] += 1

        info = f"""
Cache Information:
- Total entries: {total_entries}
- Valid entries: {valid_entries}
- Expired entries: {expired_entries}
- Age distribution:
"""
        for age_range, count in age_distribution.items():
            info += f"  {age_range}: {count}\n"

        return info.strip()

    except Exception as e:
        return f"Error reading cache: {e}"


# Initialize cache
cage_cache = load_cage_cache()
pdf_cache = {}

# Unit code to description mapping
UNIT_MAPPING = {
    'AB': 'BULK PACK', 'AC': 'ACRE', 'AD': 'DRAM (MINIM)', 'AJ': 'COP', 'AL': 'ACCESS LINES', 'AM': 'AMPOULE', 'AO': 'APOTHECARY OUNCE', 'AP': 'APOTHECARY POUND',
    'AR': 'SUPPOSITORY', 'AS': 'APOTHECARY SCRUPLE', 'AT': 'ASSORTMENT', 'AV': 'CAPSULE', 'AW': 'POWDER-FILLED VIALS', 'AX': 'TWENTY', 'AY': 'ASSEMBLY', 'B0': 'BRITISH THERMAL UNITS (BTU\'S) PER CUBIC FOOT',
    'B1': 'BARREL, LIQUID', 'B2': 'BARREL, DRY', 'B3': 'BATTING POUND', 'B4': 'BARREL, IMPERIAL', 'B5': 'BILLET', 'B6': 'BUN', 'B7': 'CYCLE', 'B8': 'BOARD', 'B9': 'BATT',
    'BA': 'BALL', 'BB': 'BASS BOX', 'BC': 'BUCKET', 'BD': 'BUNDLE', 'BE': 'BALE', 'BF': 'BOARD FOOT', 'BG': 'BAG', 'BH': 'BRUSH', 'BI': 'BELT', 'BJ': 'BAND', 'BK': 'BOOK',
    'BL': 'BARREL', 'BM': 'BEAM', 'BN': 'BULK', 'BO': 'BOLT', 'BP': '100 BOARD FEET', 'BQ': 'BRIQUET', 'BR': 'BAR', 'BS': 'BASKET', 'BT': 'BOTTLE', 'BU': 'BUSHEL (32 DRY QUARTS)',
    'BV': 'BUSHEL, DRY IMPERIAL', 'BW': 'BASE WEIGHT', 'BX': 'BOX', 'BY': 'BUNKS', 'BZ': 'BLOCK', 'C0': 'CALLS', 'C1': 'COMPOSITE PRODUCT POUNDS (TOTAL WEIGHT)',
    'C2': 'SQUARE CENTIMETER', 'C3': 'COMBO', 'C4': 'CARLOAD', 'C5': 'COST', 'C6': 'CELL', 'C7': 'CARSET', 'C8': 'CUBIC DECIMETER', 'C9': 'COIL GROUP', 'CA': 'CARTRIDGE', 'CB': 'CARBOY',
    'CC': 'CUBIC CENTIMETER', 'CD': 'CUBIC YARD', 'CE': 'CONE', 'CF': 'CUBIC FOOT', 'CG': 'CENTIGRAM', 'CH': 'CHAINS (LAND SURVEY)', 'CI': 'CUBIC INCH', 'CK': 'CAKE', 'CL': 'COIL',
    'CM': 'CENTIMETER', 'CN': 'CAN', 'CO': 'CONTAINER', 'CP': 'CRATE', 'CQ': 'CARD', 'CR': 'CONNECTOR', 'CS': 'CASE', 'CT': 'CARTON', 'CU': 'CURIE', 'CV': 'COVER', 'CW': 'HUNDRED WEIGHT (LONG)', 'CX': 'CASSETTE',
    'CY': 'CYLINDER', 'CZ': 'CUBIC METER', 'DA': 'DAYS', 'DB': 'DECIBELS', 'DC': 'DECAGRAM', 'DE': 'DECIMETER', 'DF': 'FAHRENHEIT', 'DG': 'DECIGRAM', 'DI': 'DISPENSER', 'DK': 'KELVIN', 'DL': 'DECILITER',
    'DM': 'DRAM', 'DO': 'DOLLARS, U.S.', 'DP': 'DOZEN PAIR', 'DQ': 'DATA RECORD', 'DR': 'DRUM', 'DS': 'DISPLAY', 'DT': 'DRY TON', 'DU': 'DYNE', 'DW': 'PENNYWEIGHT', 'DX': 'CALENDAR DAYS (NUMBER OF)', 'DY': 'DIRECTORY BOOKS',
    'DZ': 'DOZEN', 'E1': 'HECTOMETER', 'EA': 'EACH', 'EB': 'ELECTRONIC MAIL BOXES', 'EE': 'EMPLOYEES', 'EH': 'KNOTS', 'EJ': 'LOCATIONS', 'EP': 'ELEVEN PACK', 'EQ': 'EQUIVALENT GALLONS', 'EV': 'ENVELOPE',
    'EX': 'EXPOSURE', 'F4': 'MINIM', 'F6': 'PRICE PER SHARE', 'FA': 'FATHOM', 'FB': 'FIELDS', 'FD': 'FOLD', 'FE': 'TRACK FOOT', 'FF': 'HUNDRED CUBIC METERS', 'FG': 'TRANSDERMAL PATCH', 'FJ': 'SIZING FACTOR',
    'FK': 'FIBERS', 'FL': 'FLAKE TON', 'FM': 'MILLION CUBIC FEET', 'FO': 'FLUID OUNCE', 'FR': 'FRAME', 'FT': 'FOOT', 'FU': 'FURLONG', 'FV': 'FIVE', 'FY': 'FIFTY', 'GB': 'U.S. GALLONS PER MINUTE',
    'GG': 'GREAT GROSS', 'GI': 'GILL', 'GL': 'GALLON', 'GM': 'GRAM', 'GN': 'GRAIN', 'GP': 'GROUP', 'GR': 'GROSS', 'GT': 'THOUSAND GALLONS PER DAY', 'GX': 'APOTHECARY GRAIN', 'H2': 'HALF LITER',
    'H4': 'HECTOLITER', 'HA': 'HUNDRED CUBIC FEET', 'HB': 'HOSPITAL BEDS', 'HC': 'HUNDRED COUNT', 'HD': 'HUNDRED', 'HF': 'HUNDRED FEET', 'HG': 'HECTOGRAM', 'HH': 'HOGSHEAD', 'HI': 'HUNDRED SHEETS',
    'HK': 'HANK', 'HL': 'HUNDRED FEET - LINEAR', 'HO': 'HUNDRED TROY OUNCES', 'HP': 'HUNDRED POUNDS', 'HQ': 'HECTARE', 'HR': 'HOUR', 'HS': 'HUNDRED SQUARE FEET', 'HT': 'HALF HOUR', 'HW': 'HUNDRED WEIGHT - SHORT (HUNDRED WEIGHT)',
    'HX': 'HUNDRED BOXES', 'HY': 'HUNDRED YARDS', 'HZ': 'HALF DOZEN', 'I1': 'PERSONS, CAPACITY', 'IG': 'IMPERIAL GALLON', 'IH': 'INHALER', 'IM': 'IMPRESSIONS', 'IN': 'INCH',
    'IP': 'INSURANCE POLICY', 'IS': 'STOPS', 'IU': 'INTERNATIONAL UNIT', 'JB': 'JOB', 'JG': 'JUG', 'JO': 'JOINT', 'JR': 'JAR', 'JU': 'JUMBO', 'K2': 'SQUARE KILOMETER', 'K6': 'KILOLITER',
    'K7': 'KILOWATT', 'KC': 'KILOCURIE', 'KE': 'KEG', 'KF': 'KILOPACKETS', 'KG': 'KILOGRAM', 'KH': 'HUNDRED KILOGRAMS', 'KK': '100 KILOGRAMS', 'KM': 'KILOMETER',
    'KR': 'KARAT (CARAT)', 'KT': 'KIT', 'KU': 'TASK', 'KV': 'KILOVOLTS', 'KZ': 'KILOWATT-HOUR', 'L5': 'LITERS AT 15 DEGREES CELSIUS', 'LB': 'POUND (AVOIRDUPOIS)', 'LE': 'LITE',
    'LF': 'LINEAR FOOT', 'LG': 'LENGTH', 'LI': 'LITER', 'LJ': 'LARGE SPRAY', 'LK': 'LINK', 'LM': 'LINEAR METER', 'LN': 'LINEAR INCH', 'LO': 'LONG TON', 'LR': 'LAYER(S)', 'LS': 'LUMP SUM', 'LT': 'LOT',
    'LY': 'LINEAR YARD', 'M0': 'MAGNETIC TAPES', 'M2': 'SQUARE MILE', 'M3': 'MAT', 'M5': 'MICROGRAM', 'M6': 'METRIC TON', 'MA': 'METRIC NET TON', 'MB': 'BRITISH THERMAL UNITS (BTUS) PER HOUR',
    'MC': 'THOUSAND CUBIC FEET', 'MD': 'AIR DRY METRIC TON', 'ME': 'MEAL', 'MF': 'THOUSAND FEET', 'MG': 'MILLIGRAM', 'MH': 'METRIC', 'MI': 'MILE', 'MJ': 'METRIC GROSS TON', 'MK': 'METRIC LONG TON',
    'ML': 'MILLILITER', 'MM': 'MILLIMETER', 'MO': 'MONTHS', 'MQ': '1000 METERS', 'MR': 'METER', 'MS': 'SQUARE MILLIMETER', 'MT': 'MINUTES', 'MX': 'THOUSAND', 'MZ': 'MIXED', 'N2': 'NUMBER OF LINES',
    'N7': 'PARTS', 'N9': 'CARTRIDGE NEEDLE', 'NA': 'MILLIGRAMS PER KILOGRAM', 'NB': 'BARGE', 'NC': 'CAR', 'ND': 'NET BARRELS', 'NE': 'NET LITERS', 'NF': 'MESSAGES', 'NG': 'NET GALLONS',
    'NI': 'NET IMPERIAL GALLONS', 'NJ': 'NUMBER OF SCREENS', 'NK': 'NIGHTS', 'NL': 'LOAD', 'NM': 'NAUTICAL MILE', 'NN': 'TRAIN', 'NS': 'SHORT TON', 'NT': 'TRAILER', 'NV': 'VEHICLE',
    'NX': 'PARTS PER THOUSAND', 'OA': 'PANEL', 'OC': 'BILLBOARD', 'OL': 'OUTLET', 'OP': 'TWO PACK', 'OT': 'OUTFIT', 'OU': 'OPERATING UNIT', 'OZ': 'OUNCE - AV', 'P0': 'PAGES - ELECTRONIC',
    'P1': 'PERCENT', 'P2': 'POUNDS PER FOOT', 'P3': 'THREE PACK', 'P4': 'FOUR-PACK', 'P5': 'FIVE-PACK', 'P6': 'SIX PACK', 'P7': 'SEVEN PACK', 'P8': 'EIGHT-PACK', 'P9': 'NINE PACK',
    'PA': 'PAGE', 'PB': 'PAIR INCHES', 'PC': 'PIECE', 'PD': 'PAD', 'PE': 'POUNDS EQUIVALENT', 'PF': 'PALLET (LIFT)', 'PG': 'PACKAGE', 'PH': 'PACK (PAK)', 'PI': 'PILLOW', 'PJ': 'PALLET/UNIT LOAD',
    'PK': 'PECK, DRY U.S.', 'PL': 'PAIL', 'PM': 'PLATE', 'PN': 'PERSON', 'PO': 'POUNDS GROSS', 'PP': 'PINT, IMPERIAL', 'PQ': 'PECK DRY IMPERIAL', 'PR': 'PAIR', 'PS': 'POUNDS NET',
    'PT': 'PINT', 'PU': 'MASS POUNDS', 'PV': 'HALF PINT', 'PX': 'PELLET', 'PY': 'PITCH', 'PZ': 'PACKET', 'QC': 'CHANNEL', 'QE': 'PHOTOGRAPHS', 'QF': 'QUARTER', 'QI': 'QUART, IMPERIAL',
    'QK': 'QUARTER KILOGRAM', 'QR': 'QUIRE', 'QS': 'QUART, DRY U.S.', 'QT': 'QUART', 'QU': 'QUARTER DOZEN', 'R4': 'CALORIE', 'R5': 'THOUSANDS OF DOLLARS', 'R9': 'THOUSAND CUBIC METERS',
    'RA': 'RATION', 'RB': 'RADIAN', 'RC': 'ROD (AREA) - 16.25 SQUARE YARDS', 'RD': 'ROUND', 'RG': 'RING', 'RH': 'RUNNING OR OPERATING HOURS', 'RK': 'ROLL-METRIC MEASURE', 'RL': 'REEL',
    'RM': 'REAM', 'RN': 'REAM-METRIC MEASURE', 'RO': 'ROLL', 'RP': 'POUNDS PER REAM', 'RR': 'RACK', 'RS': 'RESETS', 'RT': 'REVENUE TON MILES', 'RU': 'RUN', 'RX': 'THOUSAND ROUNDS',
    'S5': 'SIXTY-FOURTHS OF AN INCH', 'S6': 'SESSIONS', 'S7': 'STORAGE UNITS', 'S8': 'SHELF PACKAGE', 'S9': 'SLIP SHEET', 'SA': 'SANDWICH', 'SB': 'SHIPMENT', 'SC': 'SECONDS', 'SD': 'SKID',
    'SE': 'SET', 'SF': 'SQUARE FOOT', 'SG': 'SEGMENT', 'SH': 'SHEET', 'SI': 'SQUARE INCH', 'SJ': 'SACK', 'SK': 'SKEIN', 'SL': 'SPOOL', 'SM': 'SQUARE METER', 'SN': 'SECTION (640 ACRES OR ONE SQUARE MILE)', 'SO': 'SHOT',
    'SP': 'STRIP', 'SQ': 'SQUARE', 'SR': 'SPLIT TANKTRUCK', 'SS': 'SHEET-METRIC MEASURE', 'ST': 'SEAT', 'SU': 'SQUARE ROD', 'SV': 'SERVICE', 'SW': 'STANDARD ADVERTISING UNITS (SAUS)',
    'SX': 'STICK', 'SY': 'SQUARE YARD', 'SZ': 'SYRINGE', 'T1': 'THOUSAND POUNDS GROSS', 'T2': 'TEASPOON', 'T3': 'THOUSAND PIECES', 'T4': 'THOUSAND BAGS', 'T5': 'THOUSAND CASINGS',
    'T6': 'THOUSAND GALLONS', 'T7': 'THOUSAND IMPRESSIONS', 'T8': 'THOUSAND LINEAR INCHES', 'T9': 'THOUSAND KILOWATT HOURS/MEGAWATT-HOUR', 'TA': 'TENTH CUBIC FOOT', 'TB': 'TABLESPOON',
    'TC': 'TRUCKLOAD', 'TD': 'TWENTY-FOUR', 'TE': 'TEN', 'TF': 'TWENTY-FIVE', 'TG': 'GROSS TON', 'TH': 'THOUSAND KILOGRAMS', 'TI': 'THOUSAND SQUARE INCHES', 'TJ': 'THOUSAND SQ. CENTIMETERS', 'TK': 'TANK',
    'TL': 'THOUSAND LINEAR METERS', 'TM': 'THOUSAND FEET (BOARD)', 'TN': 'NET TON (2,000 POUNDS)', 'TO': 'TROY OUNCE', 'TP': 'TROY POUND', 'TQ': 'THOUSAND FEET', 'TR': 'TEN SQUARE FEET',
    'TS': 'THIRTY-SIX', 'TT': 'TABLET', 'TU': 'TUBE', 'TV': 'TEN-PACK', 'TW': 'THOUSAND SHEETS', 'TX': 'THOUSAND LINEAR YARDS', 'TY': 'TRAY', 'TZ': 'THOUSAND SQUARE FEET', 'U1': 'TREATMENTS',
    'U5': 'TWO HUNDRED FIFTY', 'U6': 'U.S. GALLONS AT 60 DEGREES FAHRENHEIT', 'UH': 'TEN THOUSAND YARDS', 'UL': 'UNITLESS', 'UM': 'MILLION UNITS', 'UN': 'UNIT', 'UP': 'TROCHE',
    'UQ': 'WAFER', 'US': 'UNITED STATES PHARMACOPOEIA (USP)UNIT', 'V1': 'FLAT', 'V2': 'POUCH', 'VC': 'FIVE HUNDRED', 'VI': 'VIAL', 'VS': 'VISIT', 'VT': 'VOLT', 'W2': 'WET KILO',
    'WB': 'WET POUND', 'WD': 'WORK DAYS', 'WE': 'WET TON', 'WG': 'WINE GALLON', 'WH': 'WHEEL', 'WK': 'WEEK', 'WR': 'WRAP', 'WT': 'WATT', 'X2': 'BUNCH', 'X3': 'CLOVE', 'X4': 'DROP',
    'X5': 'HEAD', 'X6': 'HEART', 'X7': 'LEAF', 'X8': 'LOAF', 'X9': 'PORTION', 'Y1': 'SLICE', 'Y4': 'TUB', 'YD': 'YARD', 'YL': '100 LINEAR YARDS', 'YR': 'YEARS', 'YS': 'SLEEVE', 'YT': 'BYTES',
    'Z1': 'LIFT VAN', 'Z2': 'CHEST', 'Z3': 'CASK', 'Z5': 'LUG', 'ZF': 'MILLION BTUS/DEKATHERM'
}


def check_for_hang():
    global last_active
    if time.time() - last_active > TIMEOUT_THRESHOLD:
        raise RuntimeError("Script appears to be hung - restarting")
    last_active = time.time()


def cleanup_resources(driver):
    try:
        while len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
        gc.collect()
    except Exception as e:
        print(f"Cleanup error: {e}")


def retry(max_attempts=2, delay=2, cleanup_func=None):
    def decorator(func):
        def wrapper(*args, **kwargs):
            attempts = 0
            last_exception = None
            while attempts < max_attempts:
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    attempts += 1
                    last_exception = e
                    print(f"Attempt {attempts} failed: {str(e)}")

                    if cleanup_func:
                        try:
                            # Pass the driver (first positional arg) to cleanup, if available
                            driver_arg = args[0] if args else None
                            cleanup_func(driver_arg) if driver_arg is not None else cleanup_func()
                        except Exception as ce:
                            print(f"Cleanup failed: {ce}")

                    if attempts >= max_attempts:
                        raise last_exception
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


def initialize_driver():
    """Initialize WebDriver with optimized settings and GPU error suppression"""
    max_retries = 2
    retry_count = 0

    # Suppress Chrome GPU error messages
    import os
    os.environ['CHROME_LOG_FILE'] = 'NUL'  # Windows

    while retry_count < max_retries:
        try:
            # Use a random port to avoid conflicts
            service = Service(
                executable_path=ChromeDriverManager().install(),
                port=random.randint(10000, 20000),
                service_args=['--verbose', '--log-path=NUL']
            )

            chrome_options = get_optimized_chrome_options()

            # Additional options for GPU error suppression
            chrome_options.add_experimental_option(
                'useAutomationExtension', False)
            chrome_options.add_experimental_option(
                "excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option(
                'excludeSwitches', ['enable-logging'])

            # Suppress DevTools messages
            chrome_options.add_experimental_option("detach", False)

            driver = webdriver.Chrome(service=service, options=chrome_options)

            # OPTIMIZED TIMEOUTS
            driver.set_page_load_timeout(20)
            driver.implicitly_wait(3)

            # Test driver functionality
            driver.get("about:blank")
            print("WebDriver initialized successfully")
            return driver

        except Exception as e:
            retry_count += 1
            print(
                f"WebDriver initialization attempt {retry_count} failed: {str(e)}")
            if retry_count >= max_retries:
                raise RuntimeError(
                    f"Failed to initialize WebDriver after {max_retries} attempts")
            time.sleep(3)


def safe_get(driver, url, max_retries=2):
    """Safe page loading with SSL error handling"""
    retries = 0
    while retries < max_retries:
        try:
            driver.set_page_load_timeout(20)
            driver.get(url)
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script('return document.readyState') == 'complete')
            return True
        except TimeoutException:
            print(f"Timeout loading {url}, retrying...")
            retries += 1
            try:
                driver.execute_script("window.stop();")
            except:
                pass
            time.sleep(2)
        except Exception as e:
            print(f"Page load failed (attempt {retries + 1}): {str(e)}")
            retries += 1
            time.sleep(2)
    return False


def parse_scrape_date(date_str):
    """
    Parse a DIBBS date string into a Python date.

    The RFQ dates table can show dates in different formats (e.g. 02-06-2026 or 02/06/2026),
    while our command-line argument and Django side typically use MM-DD-YYYY.
    This helper tries multiple common formats before giving up.
    """
    if not date_str:
        return None

    candidates = [
        "%m-%d-%Y",  # 02-06-2026
        "%m/%d/%Y",  # 02/06/2026
    ]
    for fmt in candidates:
        try:
            return datetime.datetime.strptime(date_str, fmt).date()
        except Exception:
            continue
    print(f"Warning: could not parse scrape date '{date_str}' with any known format")
    return None


# Constants
WEBSITE_URL = "https://www.dibbs.bsm.dla.mil/RFQ"

# Initialize data storage lists
row_data_list = []
nsn_data_list = []
extracted_data = []
cage_details_list = []


def check_driver_health(driver):
    """Check if WebDriver connection is healthy"""
    try:
        driver.execute_script("return true;")
        return True
    except:
        return False


def extract_quantity(raw_quantity):
    """Extract integer quantity from raw string like 'QTY: 12'. Returns 0 if not found."""
    try:
        q = raw_quantity.split("QTY:")[1].strip()
        return int(re.sub(r"[^\d]", "", q)) if q else 0
    except Exception:
        return 0


def click_element(wait, locator, by=By.ID):
    """Click on an element using WebDriverWait."""
    element = wait.until(EC.element_to_be_clickable((by, locator)))
    element.click()

# PDF EXTRACTION


def clean_prep_for_delivery_text(text):
    """Remove continuation-sheet noise from the PREP FOR DELIVERY block."""
    if not text:
        return ""

    cleaned_lines = []
    skip_patterns = [
        r"^---\s*PAGE\s+\d+\s*---$",
        r"^CONTINUATION\s+SHEET\b",
        r"^REFERENCE\s+NO\.\s+OF\s+DOCUMENT\b",
        r"^[A-Z0-9]{5,}-\d{2}-[A-Z]-\d{3,}\b",
        r"^SECTION\s+B$",
        r"^PR:\s*.*\bCONT'?D\b",
    ]

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        if any(re.search(pattern, line, re.IGNORECASE) for pattern in skip_patterns):
            continue

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def extract_prep_for_delivery(full_text):
    """Extract the multi-line PREP FOR DELIVERY block from RFQ PDF text."""
    if not full_text:
        return ""

    label_pattern = re.compile(r"PREP\s+FOR\s+DELIVERY\s*:\s*", re.IGNORECASE)
    match = label_pattern.search(full_text)
    if not match:
        return ""

    block = full_text[match.end():]

    # Primary boundary: DIBBS separator row of many stars (e.g. "* * * * * ...").
    stars_separator_match = re.search(
        r"(?m)^\s*(?:\*\s*){20,}\*?\s*$",
        block
    )
    if stars_separator_match:
        block = block[:stars_separator_match.start()]
    else:
        # Fallback boundary: later major sections or shipping/address blocks.
        stop_match = re.search(
            r"\n\s*(?:"
            r"SECTION\s+[C-Z]\b|"
            r"CONTRACT\s+CLAUSES\b|"
            r"CLAUSES\s+INCORPORATED\b|"
            r"PARCEL\s+POST\s+ADDRESS\s*:|"
            r"FREIGHT\s+SHIPPING\s+ADDRESS\s*:|"
            r"NEED\s+SHIP\s+DATE\s*:|"
            r"ORIGINAL\s+REQUIRED\s+DELIVERY\s+DATE\s*:|"
            r"FOR\s+TRANSPORTATION\s+SEE\b|"
            r"CONTINUED\s+ON\s+NEXT\s+PAGE\b"
            r")",
            block,
            re.IGNORECASE
        )
        if stop_match:
            block = block[:stop_match.start()]

    return clean_prep_for_delivery_text(block)


@retry(max_attempts=5, delay=3)
def extract_higher_level_quality_indicator(pdf_text):
    """Extract DLA export field 117 (Higher-Level Quality Indicator) from solicitation PDF text.

    Returns one of the codes from Solicitation.HIGHER_LEVEL_QUALITY_INDICATOR_CHOICES:
      'N' — no RQ001 clause in the PDF (Not Applicable)
      '8' — RQ001 present and Section A references SAE AS9100
      '7' — RQ001 present and Section A references ISO 9001:2015
      '6' — RQ001 present and Section A references SAE AS9003 or "ISO 9001 tailored"
      ''  — RQ001 present but no recognizable standard text (let the user fill in)
    """
    if not pdf_text:
        return ""
    upper = pdf_text.upper()
    if "RQ001" not in upper:
        return "N"
    if "AS9100" in upper:
        return "8"
    if "ISO 9001:2015" in upper or "ISO 9001-2015" in upper:
        return "7"
    if (
        "AS9003" in upper
        or "ISO 9001 TAILORED" in upper
        or re.search(r"TAILORED\s+TO\s+.{0,40}AS9003", upper)
    ):
        return "6"
    return ""


def extract_unit_from_pdf_comprehensive(pdf_url, driver, max_pdf_retries=3):
    """Enhanced PDF extraction with comprehensive retry logic"""
    unit = "N/A"
    inspection_point = ""
    acceptance_point = ""
    deliver_fob = ""
    deliver_days = ""
    buyer_info = ""
    prep_for_delivery = ""
    solicitation_line_number = ""
    procurement_history = []
    higher_level_quality_indicator = ""

    print(f"\nExtracting from PDF: {pdf_url}")

    # ENHANCED PDF RETRY LOGIC
    for pdf_attempt in range(max_pdf_retries):
        try:
            print(
                f"PDF processing attempt {pdf_attempt + 1}/{max_pdf_retries}")

            # Get cookies from Selenium session
            cookies = {c['name']: c['value'] for c in driver.get_cookies()}

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://www.dibbs.bsm.dla.mil/',
                'Accept': '*/*',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }

            # Download with multiple retry strategies
            pdf_content = None
            download_attempts = 3

            for attempt in range(download_attempts):
                try:
                    print(
                        f"  PDF download attempt {attempt + 1}/{download_attempts}")

                    response = warp_get(
                        pdf_url,
                        cookies=cookies,
                        headers=headers,
                        verify=False,
                        stream=True,
                        timeout=45,
                        allow_redirects=True
                    )

                    if response is None:
                        print(f"  WARP GET returned None for {pdf_url}")
                        if attempt < download_attempts - 1:
                            time.sleep(2 ** attempt)
                            continue
                        else:
                            raise Exception(
                                f"WARP GET failed after {download_attempts} attempts")

                    try:
                        if response.status_code != 200:
                            print(f"  HTTP error: {response.status_code}")
                            if attempt < download_attempts - 1:
                                time.sleep(2 ** attempt)
                                continue
                            else:
                                raise Exception(
                                    f"HTTP {response.status_code} after {download_attempts} attempts")

                        pdf_content = response.content

                        # Verify PDF signature
                        if not pdf_content.startswith(b'%PDF'):
                            pdf_sig_pos = pdf_content.find(b'%PDF', 0, 1024)
                            if pdf_sig_pos >= 0:
                                pdf_content = pdf_content[pdf_sig_pos:]
                            else:
                                raise Exception(
                                    f"Invalid PDF content on attempt {attempt + 1}")

                        print(
                            f"  Successfully downloaded PDF: {len(pdf_content)} bytes")
                        break
                    finally:
                        # Ensure response is closed when using stream=True
                        if hasattr(response, 'close'):
                            response.close()

                except Exception as e:
                    print(f"  Download attempt {attempt + 1} failed: {e}")
                    if attempt < download_attempts - 1:
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        raise

            if not pdf_content or not b'%PDF' in pdf_content[:1024]:
                raise Exception("Failed to download valid PDF content")

            # PDF PROCESSING with error handling
            try:
                with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                    print(
                        f"  Successfully opened PDF with {len(pdf.pages)} pages")

                    full_text = ""
                    page_texts = []

                    # Extract text from first 15 pages
                    for page_num, page in enumerate(pdf.pages[:15], 1):
                        try:
                            text = page.extract_text() or ""
                            if text:
                                page_texts.append(text)
                                full_text += f"\n--- PAGE {page_num} ---\n{text}"
                                print(
                                    f"  Extracted text from page {page_num}: {len(text)} characters")

                                # UNIT EXTRACTION - Multiple patterns
                                if unit == "N/A":
                                    # Pattern 1: ITEM NO. SUPPLIES/SERVICES QUANTITY UNIT UNIT PRICE AMOUNT
                                    pattern1 = re.compile(
                                        r"^\d+\s+\d{4}-\d{2}-\d{3}-\d{4}\s+\d+\.\d{3}\s+([A-Z]{2})\s+\$",
                                        re.MULTILINE
                                    )
                                    match1 = pattern1.search(text)
                                    if match1:
                                        unit = match1.group(1).upper()
                                        print(
                                            f"  Found unit via Pattern1 on page {page_num}: {unit}")

                                    # Pattern 2: CLIN PR PRLI UI QUANTITY UNIT PRICE TOTAL PRICE
                                    pattern2 = re.compile(
                                        r"^\d+\s+\d+\s+\d+\s+([A-Z]{2})\s+[\d,]+\.\d{3}",
                                        re.MULTILINE
                                    )
                                    match2 = pattern2.search(text)
                                    if match2:
                                        unit = match2.group(1).upper()
                                        print(
                                            f"  Found unit via Pattern2 (UI) on page {page_num}: {unit}")

                                    # Fallback patterns for unit
                                    fallback_patterns = [
                                        r"QTY:\s*\d+\s+([A-Z]{2})\b",
                                        r"UNIT\s*[:=]\s*([A-Z]{2})\b",
                                        r"U/I\s*[:=]\s*([A-Z]{2})\b",
                                        r"\b(\d+)\s+([A-Z]{2})\s+@",
                                        r"Quantity\s*:\s*\d+\s+([A-Z]{2})\b",
                                        r"UNIT\s+OF\s+ISSUE\s*[:=]\s*([A-Z]{2})\b"
                                    ]

                                    for pattern in fallback_patterns:
                                        matches = re.finditer(
                                            pattern, text, re.IGNORECASE)
                                        for match in matches:
                                            unit_candidate = match.group(
                                                1) if match.lastindex else match.group(0)
                                            if unit_candidate.upper() in UNIT_MAPPING:
                                                unit = unit_candidate.upper()
                                                print(
                                                    f"  Found unit on page {page_num} via fallback pattern: {unit}")
                                                break
                                        if unit != "N/A":
                                            break

                                    # Table extraction fallback for unit and line number
                                    tables = page.extract_tables()
                                    for table in tables:
                                        if len(table) > 1:
                                            headers = [str(cell).upper().strip()
                                                       for cell in table[0]]
                                            unit_col = None
                                            line_col = None
                                            
                                            # Find unit column
                                            if "UNIT" in headers:
                                                unit_col = headers.index(
                                                    "UNIT")
                                            elif "UI" in headers:
                                                unit_col = headers.index("UI")
                                            
                                            # Find line number column
                                            if "LINE" in headers:
                                                line_col = headers.index("LINE")
                                            elif "LINE NO" in headers or "LINE NUMBER" in headers:
                                                for idx, h in enumerate(headers):
                                                    if "LINE" in h:
                                                        line_col = idx
                                                        break
                                            elif "PRLI" in headers:
                                                line_col = headers.index("PRLI")
                                            elif "PR LI" in headers:
                                                line_col = headers.index("PR LI")

                                            if unit_col is not None:
                                                for row in table[1:]:
                                                    if len(row) > unit_col and row[unit_col]:
                                                        unit_candidate = str(
                                                            row[unit_col]).strip().upper()
                                                        if unit_candidate in UNIT_MAPPING:
                                                            unit = unit_candidate
                                                            print(
                                                                f"  Found unit in table on page {page_num}: {unit}")
                                                            
                                                            # Extract line number from same row if column exists
                                                            if line_col is not None and len(row) > line_col and row[line_col]:
                                                                solicitation_line_number = str(row[line_col]).strip()
                                                                print(
                                                                    f"  Found line number in table on page {page_num}: {solicitation_line_number}")
                                                            break
                                                if unit != "N/A":
                                                    break
                                            
                                            # If unit not found but line number column exists, try to extract line number
                                            if not solicitation_line_number and line_col is not None:
                                                for row in table[1:]:
                                                    if len(row) > line_col and row[line_col]:
                                                        solicitation_line_number = str(row[line_col]).strip()
                                                        print(
                                                            f"  Found line number in table on page {page_num}: {solicitation_line_number}")
                                                        break
                                            
                                            # Extract PROCUREMENT HISTORY table
                                            # Look for table with headers: CAGE, Contract Number, Quantity, Unit Cost, AWD Date, Surplus Material
                                            proc_history_headers = [str(h).upper().strip() for h in headers]
                                            headers_joined = " ".join(proc_history_headers)
                                            
                                            has_cage_col = "CAGE" in proc_history_headers
                                            has_contract_col = "CONTRACT" in headers_joined
                                            has_quantity_col = "QUANTITY" in proc_history_headers
                                            has_unit_cost_col = "UNIT COST" in headers_joined or "UNITCOST" in headers_joined.replace(" ", "")
                                            has_awd_date_col = "AWD DATE" in headers_joined or "AWD" in proc_history_headers
                                            has_surplus_col = "SURPLUS" in headers_joined
                                            
                                            # If this looks like a procurement history table (must have CAGE, Contract, Quantity, Unit Cost)
                                            if has_cage_col and has_contract_col and has_quantity_col and has_unit_cost_col:
                                                # Find column indices - handle variations in header names
                                                cage_idx = next((i for i, h in enumerate(proc_history_headers) if h == "CAGE"), None)
                                                
                                                # Contract Number might be "CONTRACT NUMBER", "CONTRACT", or split across cells
                                                contract_idx = None
                                                for i, h in enumerate(proc_history_headers):
                                                    if "CONTRACT" in h:
                                                        contract_idx = i
                                                        break
                                                
                                                quantity_idx = next((i for i, h in enumerate(proc_history_headers) if h == "QUANTITY"), None)
                                                
                                                # Unit Cost might be "UNIT COST" or "UNITCOST" or split
                                                unit_cost_idx = None
                                                for i, h in enumerate(proc_history_headers):
                                                    h_clean = h.replace(" ", "")
                                                    if "UNITCOST" in h_clean or ("UNIT" in h and "COST" in h):
                                                        unit_cost_idx = i
                                                        break
                                                
                                                # AWD Date might be "AWD DATE", "AWD", or split
                                                awd_date_idx = None
                                                for i, h in enumerate(proc_history_headers):
                                                    if "AWD" in h:
                                                        awd_date_idx = i
                                                        break
                                                
                                                # Surplus Material might be "SURPLUS MATERIAL" or "SURPLUS"
                                                surplus_idx = None
                                                for i, h in enumerate(proc_history_headers):
                                                    if "SURPLUS" in h:
                                                        surplus_idx = i
                                                        break
                                                
                                                # Extract first 4 data rows from this table only
                                                print(f"  Detected procurement history table on page {page_num}")
                                                print(f"    Column indices - CAGE: {cage_idx}, Contract: {contract_idx}, Quantity: {quantity_idx}, Unit Cost: {unit_cost_idx}, AWD Date: {awd_date_idx}, Surplus: {surplus_idx}")
                                                
                                                max_records = 4  # Limit to first 4 records
                                                records_extracted = 0
                                                
                                                for row_idx, row in enumerate(table[1:], 1):
                                                    # Stop if we've already extracted 4 records
                                                    if records_extracted >= max_records:
                                                        print(f"    Reached limit of {max_records} procurement history records")
                                                        break
                                                    
                                                    # Skip empty rows
                                                    if not row or all(not cell or str(cell).strip() == "" for cell in row):
                                                        continue
                                                    
                                                    # Check if row has enough columns
                                                    max_required_idx = max([i for i in [cage_idx, contract_idx, quantity_idx, unit_cost_idx] if i is not None], default=-1)
                                                    if len(row) <= max_required_idx:
                                                        continue
                                                    
                                                    proc_record = {}
                                                    if cage_idx is not None and len(row) > cage_idx and row[cage_idx]:
                                                        proc_record['cage'] = str(row[cage_idx]).strip()
                                                    if contract_idx is not None and len(row) > contract_idx and row[contract_idx]:
                                                        proc_record['contract_number'] = str(row[contract_idx]).strip()
                                                    if quantity_idx is not None and len(row) > quantity_idx and row[quantity_idx]:
                                                        proc_record['quantity'] = str(row[quantity_idx]).strip()
                                                    if unit_cost_idx is not None and len(row) > unit_cost_idx and row[unit_cost_idx]:
                                                        proc_record['unit_cost'] = str(row[unit_cost_idx]).strip()
                                                    if awd_date_idx is not None and len(row) > awd_date_idx and row[awd_date_idx]:
                                                        proc_record['awd_date'] = str(row[awd_date_idx]).strip()
                                                    if surplus_idx is not None and len(row) > surplus_idx and row[surplus_idx]:
                                                        proc_record['surplus_material'] = str(row[surplus_idx]).strip()
                                                    
                                                    # Only add if we have at least CAGE and Contract Number (required fields)
                                                    if proc_record.get('cage') and proc_record.get('contract_number'):
                                                        procurement_history.append(proc_record)
                                                        records_extracted += 1
                                                        print(f"    Extracted row {row_idx} ({records_extracted}/{max_records}): CAGE={proc_record.get('cage')}, Contract={proc_record.get('contract_number')[:20]}...")
                                                
                                                if procurement_history:
                                                    print(f"  Successfully extracted {len(procurement_history)} procurement history records (limited to first {max_records}) from page {page_num}")

                        except Exception as page_error:
                            print(
                                f"  Error extracting text from page {page_num}: {page_error}")
                            continue

                    if not full_text.strip():
                        raise Exception("No text extracted from any page")

                    print(
                        f"  Total text extracted: {len(full_text)} characters")

                    prep_for_delivery = extract_prep_for_delivery(full_text)
                    if prep_for_delivery:
                        print(
                            f"  Found prep for delivery: {prep_for_delivery[:80]}...")

                    # Extract LINE NUMBER / PRLI if not already found
                    if not solicitation_line_number:
                        line_number_patterns = [
                            r"LINE\s+(?:NO|NUMBER|#)?\s*[:=]\s*(\d+)",
                            r"PRLI\s*[:=]\s*(\d+)",
                            r"PR\s+LI\s*[:=]\s*(\d+)",
                            r"LINE\s+ITEM\s*[:=]\s*(\d+)",
                            r"CLIN\s+(\d+)\s+\d+\s+\d+\s+[A-Z]{2}",  # Pattern 2 format: CLIN PR PRLI UI
                            r"^\d+\s+(\d+)\s+\d+\s+[A-Z]{2}",  # First number after CLIN in table row
                        ]
                        
                        for pattern in line_number_patterns:
                            match = re.search(pattern, full_text, re.IGNORECASE | re.MULTILINE)
                            if match:
                                solicitation_line_number = match.group(1).strip()
                                print(f"  Found line number via pattern: {solicitation_line_number}")
                                break

                    # Extract INSPECTION POINT
                    inspection_patterns = [
                        r"INSPECTION\s+POINT\s*:\s*([^\n\r]+)",
                        r"INSPECTION\s+POINT\s*:\s*([A-Z\s]+)(?=\s*[A-Z\s]*:|\s*$)",
                        r"INSPECTION\s+POINT\s*:\s*([^:]+?)(?=\s*(?:ACCEPTANCE|FOB|DELIVERY|$))"
                    ]

                    for pattern in inspection_patterns:
                        match = re.search(pattern, full_text,
                                          re.IGNORECASE | re.MULTILINE)
                        if match:
                            inspection_point = match.group(1).strip()
                            print(
                                f"  Found inspection point: {inspection_point}")
                            break

                    # Extract ACCEPTANCE POINT
                    acceptance_patterns = [
                        r"ACCEPTANCE\s+POINT\s*:\s*([^\n\r]+)",
                        r"ACCEPTANCE\s+POINT\s*:\s*([A-Z\s]+)(?=\s*[A-Z\s]*:|\s*$)",
                        r"ACCEPTANCE\s+POINT\s*:\s*([^:]+?)(?=\s*(?:INSPECTION|FOB|DELIVERY|$))"
                    ]

                    for pattern in acceptance_patterns:
                        match = re.search(pattern, full_text,
                                          re.IGNORECASE | re.MULTILINE)
                        if match:
                            acceptance_point = match.group(1).strip()
                            print(
                                f"  Found acceptance point: {acceptance_point}")
                            break

                    # Extract FOB / DELIVER FOB
                    fob_patterns = [
                        r"DELIVER\s+FOB\s*:\s*([^\n\r]+)",
                        r"FOB\s*:\s*([^\n\r]+)",
                        r"DELIVER\s+FOB\s*:\s*([A-Z\s]+)(?=\s*[A-Z\s]*:|\s*$)",
                        r"FOB\s*:\s*([^:]+?)(?=\s*(?:DELIVERY|INSPECTION|ACCEPTANCE|$))"
                    ]

                    for pattern in fob_patterns:
                        match = re.search(pattern, full_text,
                                          re.IGNORECASE | re.MULTILINE)
                        if match:
                            deliver_fob = match.group(1).strip()
                            print(f"  Found deliver FOB: {deliver_fob}")
                            break

                    # Extract DELIVERY DAYS / DELIVERY DATE
                    delivery_patterns = [
                        r"DELIVERY\s*\(IN\s+DAYS\)\s*:\s*(\d+)",
                        r"DELIVERY\s+DATE\s*:\s*([^\n\r]+)",
                        r"DELIVERY\s*:\s*(\d+)\s*DAYS?",
                        r"DELIVERY\s+DAYS?\s*:\s*(\d+)",
                        r"DELIVERY\s+DATE\s*:\s*([^:]+?)(?=\s*(?:FOB|INSPECTION|ACCEPTANCE|$))"
                    ]

                    for pattern in delivery_patterns:
                        match = re.search(pattern, full_text,
                                          re.IGNORECASE | re.MULTILINE)
                        if match:
                            deliver_days = match.group(1).strip()
                            print(
                                f"  Found delivery days/date: {deliver_days}")
                            break

                    # COMPREHENSIVE BUYER INFORMATION EXTRACTION
                    print("  Searching for buyer information...")

                    # Look for ISSUED BY section first
                    issued_by_patterns = [
                        r"5\.\s*ISSUED\s+BY(.*?)(?=8\.\s*TO:)",
                        r"ISSUED\s+BY(.*?)(?=\d+\.\s*TO:)",
                        r"5\.\s*ISSUED\s+BY(.*?)(?=\d+\.\s*(?:TO|DELIVER|DESTINATION|PLEASE))",
                        r"ISSUED\s+BY(.*?)(?=\d+\.\s*[A-Z])",
                        r"ISSUED\s+BY([^$]{1,3000})"
                    ]

                    for i, pattern in enumerate(issued_by_patterns):
                        issued_by_match = re.search(
                            pattern, full_text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                        if issued_by_match:
                            issued_by_text = issued_by_match.group(1).strip()
                            print(
                                f"  Found ISSUED BY section using pattern {i+1}")

                            # Comprehensive buyer patterns
                            buyer_patterns = [
                                # New "Buyer: Name Code" patterns
                                r"Buyer:\s*(.+?)\s+([A-Z0-9]{6,})\s+Tel:\s*([0-9\-DSN]+)\s+Fax:\s*([0-9\-]+)[\s\S]*?Email:\s*([^\s\n\r]+)",
                                r"Buyer:\s*(.+?)\s+([A-Z0-9]{6,})\s+Tel:\s*([0-9\-DSN]+)[\s\S]*?Email:\s*([^\s\n\r]+)",
                                r"Buyer:\s*(.+?)\s+([A-Z0-9]{6,})\s+Tel:\s*([0-9\-DSN]+)\s+Fax:\s*([0-9\-]+)",
                                r"Buyer:\s*(.+?)\s+([A-Z0-9]{6,})\s+Tel:\s*([0-9\-DSN]+)",
                                r"Buyer:\s*(.+?)\s+([A-Z0-9]{3,})\s+Tel:\s*([0-9\-DSN]+)[\s\S]*?Email:\s*([^\s\n\r]+)",
                                r"Buyer:\s*(.+?)\s+([A-Z0-9]{3,})\s+Tel:\s*([0-9\-DSN]+)",

                                # Existing "Name: ... Buyer Code:" patterns
                                r"Name:\s*([^:]+?)\s+Buyer\s+Code:\s*([A-Z0-9]+)\s+Tel:\s*([0-9\-]+)\s+Fax:\s*([0-9\-]+)\s+Email:\s*([^\s\n\r]+)",
                                r"Name:\s*([^:]+?)\s+Buyer\s+Code:\s*([A-Z0-9]+)\s+Tel:\s*([0-9\-]+)\s+Email:\s*([^\s\n\r]+)",
                                r"Name:\s*([^:]+?)\s+Buyer\s+Code:\s*([A-Z0-9]+)\s+Tel:\s*([0-9\-DSN]+)\s+Fax:\s*([0-9\-]+).*?Email:\s*([^\s\n\r]+)",
                                r"Name:\s*([^:]+?)\s+Buyer\s+Code:\s*([A-Z0-9]+)\s+Tel:\s*([0-9\-DSN]+).*?Email:\s*([A-Za-z0-9\.\@\-\_]+)",
                                r"Name:\s*([^:]+?)\s+Buyer\s+Code:\s*([A-Z0-9]+)\s+Tel:\s*([A-Z0-9\-]+).*?Email:\s*([A-Za-z0-9\.\@\-\_]+)",
                                r"Name:\s*([^:]+?)\s+Buyer\s+Code:\s*([A-Z0-9]+)\s+Tel:\s*([^\s\n\r]+).*?Email:\s*([^\s\n\r]+)"
                            ]

                            buyer_found = False
                            for j, buyer_pattern in enumerate(buyer_patterns):
                                buyer_match = re.search(
                                    buyer_pattern, issued_by_text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                                if buyer_match:
                                    print(
                                        f"  Found buyer pattern {j+1} in ISSUED BY section")
                                    groups = buyer_match.groups()

                                    if j < 6:  # New "Buyer: Name Code" patterns
                                        name = groups[0].strip()
                                        buyer_code = groups[1].strip()
                                        tel = groups[2].strip()

                                        buyer_info = f"Name: {name} Buyer Code: {buyer_code} Tel: {tel}"

                                        if len(groups) == 5:  # Has fax and email
                                            fax = groups[3].strip()
                                            email = groups[4].strip()
                                            buyer_info += f" Fax: {fax} Email: {email}"
                                        # Has email, no fax
                                        elif len(groups) == 4 and j in [1, 4]:
                                            email = groups[3].strip()
                                            buyer_info += f" Email: {email}"
                                        # Has fax, no email
                                        elif len(groups) == 4 and j in [2]:
                                            fax = groups[3].strip()
                                            buyer_info += f" Fax: {fax}"
                                        elif len(groups) == 3:  # Only name, code, tel
                                            # Try to find fax and email separately
                                            fax_match = re.search(
                                                r"Fax:\s*([0-9\-]+)", issued_by_text, re.IGNORECASE)
                                            email_match = re.search(
                                                r"Email:\s*([^\s\n\r]+)", issued_by_text, re.IGNORECASE)
                                            if fax_match:
                                                buyer_info += f" Fax: {fax_match.group(1).strip()}"
                                            if email_match:
                                                buyer_info += f" Email: {email_match.group(1).strip()}"

                                    else:  # Existing "Name: ... Buyer Code:" patterns
                                        name = groups[0].strip()
                                        buyer_code = groups[1].strip()
                                        tel = groups[2].strip()

                                        buyer_info = f"Name: {name} Buyer Code: {buyer_code} Tel: {tel}"

                                        # Has fax
                                        if len(groups) == 5 and groups[3] and groups[4]:
                                            fax = groups[3].strip()
                                            email = groups[4].strip()
                                            buyer_info += f" Fax: {fax} Email: {email}"
                                        elif len(groups) == 4:  # No fax, last group is email
                                            email = groups[3].strip()
                                            buyer_info += f" Email: {email}"
                                        # No fax, email is in groups[4]
                                        elif len(groups) == 5 and not groups[3]:
                                            email = groups[4].strip()
                                            buyer_info += f" Email: {email}"

                                    print(
                                        f"  Successfully extracted buyer info: {buyer_info}")
                                    buyer_found = True
                                    break

                            if buyer_found:
                                break

                    # If no buyer info found in ISSUED BY, search entire document
                    if not buyer_info:
                        print(
                            "  No buyer info found in ISSUED BY section, searching entire document...")

                        anywhere_patterns = [
                            r"Buyer:\s*(.+?)\s+([A-Z0-9]{6,})\s+Tel:\s*([0-9\-DSN]+)\s+Fax:\s*([0-9\-]+)[\s\S]*?Email:\s*([^\s\n\r]+)",
                            r"Buyer:\s*(.+?)\s+([A-Z0-9]{6,})\s+Tel:\s*([0-9\-DSN]+)[\s\S]*?Email:\s*([^\s\n\r]+)",
                            r"Buyer:\s*(.+?)\s+([A-Z0-9]{6,})\s+Tel:\s*([0-9\-DSN]+)",
                            r"Name:\s*([^B]+?)\s+Buyer\s+Code:\s*([A-Z0-9]+)\s+Tel:\s*([0-9\-]+)\s+Fax:\s*([0-9\-]+)\s+Email:\s*([^\s\n\r]+)",
                            r"Name:\s*([^B]+?)\s+Buyer\s+Code:\s*([A-Z0-9]+)\s+Tel:\s*([0-9\-]+)\s+Email:\s*([^\s\n\r]+)"
                        ]

                        for k, pattern in enumerate(anywhere_patterns):
                            match = re.search(
                                pattern, full_text, re.IGNORECASE | re.MULTILINE)
                            if match:
                                print(
                                    f"  Found buyer pattern {k+1} anywhere in text")
                                groups = match.groups()

                                if k < 3:  # "Buyer: Name Code" patterns
                                    name = groups[0].strip()
                                    buyer_code = groups[1].strip()
                                    tel = groups[2].strip()
                                    buyer_info = f"Name: {name} Buyer Code: {buyer_code} Tel: {tel}"

                                    if len(groups) == 5:  # Has fax and email
                                        fax = groups[3].strip()
                                        email = groups[4].strip()
                                        buyer_info += f" Fax: {fax} Email: {email}"
                                    elif len(groups) == 4:  # Has email, no fax
                                        email = groups[3].strip()
                                        buyer_info += f" Email: {email}"
                                else:  # "Name: ... Buyer Code:" patterns
                                    buyer_info = f"Name: {groups[0].strip()} Buyer Code: {groups[1].strip()} Tel: {groups[2].strip()}"
                                    if len(groups) == 5:  # Has fax
                                        buyer_info += f" Fax: {groups[3].strip()} Email: {groups[4].strip()}"
                                    else:  # No fax
                                        buyer_info += f" Email: {groups[3].strip()}"

                                print(
                                    f"  Extracted buyer info from anywhere: {buyer_info}")
                                break

                    print(
                        f"  PDF processing successful on attempt {pdf_attempt + 1}")
                    print(
                        f"  Extracted - Unit: {unit}, Inspection: {inspection_point[:30]}...")

                    # DLA export field 117 — regex-only, deterministic. RQ001 lives in Section B,
                    # the AS9100/AS9003/ISO 9001 standard name lives in Section A; full_text holds both.
                    higher_level_quality_indicator = extract_higher_level_quality_indicator(full_text)
                    print(f"  Higher-Level Quality Indicator: {higher_level_quality_indicator or '(unknown)'}")

                    # AI-ENHANCED EXTRACTION: Use GPT-4 as fallback for missing fields
                    # Use AI if unit, line number, or procurement history are missing
                    # Unit is critical - if missing, solicitation will be skipped
                    use_ai_extraction = (unit == "N/A" or not solicitation_line_number or not procurement_history) and GPT4_PDF_EXTRACTION_AVAILABLE
                    
                    if use_ai_extraction:
                        # Determine what to extract: unit is critical, others are optional
                        extract_unit_flag = (unit == "N/A")
                        missing_fields = []
                        if unit == "N/A":
                            missing_fields.append("unit")
                        if not solicitation_line_number:
                            missing_fields.append("line_number")
                        if not procurement_history:
                            missing_fields.append("procurement_history")
                        
                        print(f"  [AI] Attempting GPT-4 extraction for missing fields: {', '.join(missing_fields)}")
                        if extract_unit_flag:
                            print("  [AI] CRITICAL: Unit extraction required - solicitation will be skipped if AI fails")
                        
                        try:
                            ai_result = extract_pdf_fields_with_gpt4(full_text, extract_unit=extract_unit_flag)
                            
                            if ai_result:
                                # Use AI results to fill missing fields
                                # CRITICAL: Unit extraction - if unit is N/A, try AI
                                if unit == "N/A" and ai_result.get('unit_of_issue'):
                                    ai_unit = ai_result['unit_of_issue'].strip().upper()
                                    # Validate unit is in UNIT_MAPPING
                                    if ai_unit in UNIT_MAPPING:
                                        unit = ai_unit
                                        print(f"  [AI] Found unit of issue: {unit} ({UNIT_MAPPING.get(unit, 'Unknown')})")
                                    else:
                                        print(f"  [AI] Extracted unit '{ai_unit}' not in UNIT_MAPPING, ignoring")
                                
                                if not solicitation_line_number and ai_result.get('solicitation_line_number'):
                                    solicitation_line_number = ai_result['solicitation_line_number']
                                    print(f"  [AI] Found line number: {solicitation_line_number}")
                                
                                if not procurement_history and ai_result.get('procurement_history'):
                                    procurement_history = ai_result['procurement_history']
                                    print(f"  [AI] Found {len(procurement_history)} procurement history records")
                                
                                # Log confidence and notes
                                confidence = ai_result.get('confidence_score')
                                notes = ai_result.get('extraction_notes', '')
                                if confidence:
                                    print(f"  [AI] Extraction confidence: {confidence:.2%}")
                                if notes:
                                    print(f"  [AI] Notes: {notes}")
                            else:
                                print("  [AI] GPT-4 extraction returned no results")
                                
                        except Exception as ai_error:
                            print(f"  [AI] GPT-4 extraction failed: {ai_error}")
                            # Continue with regex results - don't fail the whole extraction
                    else:
                        if not GPT4_PDF_EXTRACTION_AVAILABLE:
                            print("  [AI] GPT-4 extraction not available (module not imported)")
                        elif unit != "N/A" and solicitation_line_number and procurement_history:
                            print("  [AI] All fields found via regex/table extraction - skipping AI")

                    # If we get here, PDF processing was successful
                    break  # Exit the retry loop

            except Exception as pdf_processing_error:
                print(
                    f"  PDF processing error on attempt {pdf_attempt + 1}: {pdf_processing_error}")
                if pdf_attempt < max_pdf_retries - 1:
                    print(f"  Retrying PDF processing...")
                    time.sleep(3)
                    continue
                else:
                    raise

        except Exception as e:
            print(f"PDF attempt {pdf_attempt + 1} failed: {str(e)}")
            if pdf_attempt < max_pdf_retries - 1:
                print(f"Retrying entire PDF extraction process...")
                time.sleep(5)  # Wait longer between full retries
                continue
            else:
                print(
                    f"PDF extraction failed after {max_pdf_retries} attempts")
                break

    # Final logging
    print(f"PDF extraction complete:")
    print(f"Unit: {unit}")
    print(f"Line Number: {solicitation_line_number}")
    print(f"Procurement History Records: {len(procurement_history)}")
    print(f"Inspection: {inspection_point[:50]}...")
    print(f"Acceptance: {acceptance_point[:50]}...")
    print(f"Prep for Delivery: {prep_for_delivery[:50]}...")
    print(f"Buyer: {buyer_info[:50]}...")

    return unit, inspection_point, acceptance_point, deliver_fob, deliver_days, buyer_info, prep_for_delivery, solicitation_line_number, procurement_history, higher_level_quality_indicator


@retry(max_attempts=2, delay=2, cleanup_func=cleanup_resources)
def extract_data_from_page(driver, wait):
    """Extract data from the current page."""
    check_for_hang()
    rows = wait.until(EC.presence_of_all_elements_located((
        By.XPATH,
        "//tr[contains(@class, 'BgWhite') or contains(@class, 'BgSilver')]"
    )))
    for row in rows:
        try:
            # Extract quantity and purchase request number from the same cell
            # Format: "7014895472<br>QTY: 7000" or just "QTY: 7000"
            quantity_cell = row.find_element(By.XPATH, ".//td[7]/span")
            quantity_text = quantity_cell.text.strip()
            purchase_request = ""
            
            # Try to get the inner HTML to extract PR number before <br> tag
            try:
                quantity_html = quantity_cell.get_attribute("innerHTML")
                if quantity_html and "<br>" in quantity_html:
                    # Split by <br> tag - first part is PR number, second part is QTY
                    parts = quantity_html.split("<br>")
                    if len(parts) >= 2:
                        purchase_request = parts[0].strip()
                        # Keep the full QTY format for extract_quantity() function
                        qty_part = parts[1].strip()
                        quantity_text = qty_part  # Keep "QTY: 7000" format (extract_quantity expects this)
                    elif len(parts) == 1:
                        # Only PR number, no quantity
                        purchase_request = parts[0].strip()
                        quantity_text = ""
                # If no <br> tag, quantity_text already has the correct format from .text
            except Exception:
                # If innerHTML extraction fails, use text extraction as fallback
                # quantity_text from .text should already be in "QTY: 7000" format
                pass
            
            row_data = {
                "nsn": row.find_element(By.XPATH, ".//td[2]/span/a").text.strip(),
                "nsn_link": row.find_element(By.XPATH, ".//td[2]/span/a").get_attribute("href"),
                "nomenclature": row.find_element(By.XPATH, ".//td[3]/span").text.strip(),
                "solicitation": row.find_element(By.XPATH, ".//td[5]/span/a").text.strip(),
                "status": row.find_element(By.XPATH, ".//td[6]/span").text.strip(),
                "quantity": quantity_text,
                "purchase_request": purchase_request,
                "issued_date": row.find_element(By.XPATH, ".//td[8]/span").text.strip(),
                "return_by_date": row.find_element(By.XPATH, ".//td[9]/span").text.strip(),
            }
            row_data_list.append(row_data)
        except Exception as e:
            print(f"Error processing row: {e}")


def check_if_single_page(driver):
    """Check if there's only one page of results."""
    try:
        pagination_elements = driver.find_elements(
            By.XPATH, "//tr[@class='pagination']")
        if not pagination_elements:
            return True

        page_links = driver.find_elements(
            By.XPATH, "//tr[@class='pagination']//td/a[contains(@href, 'Page')]")
        if not page_links:
            return True

        ellipsis_links = driver.find_elements(
            By.XPATH, "//tr[@class='pagination']//td/a[text()='...']")

        if page_links or ellipsis_links:
            return False

        return True

    except Exception as e:
        print(f"Error checking pagination: {e}")
        return True


@retry(max_attempts=2, delay=2, cleanup_func=cleanup_resources)
def handle_pagination(driver, wait):
    """OPTIMIZED pagination with faster processing"""
    page_number = 1

    print(f"Processing page {page_number}...")
    # Update progress to show we're on page 1
    update_progress(
        stage="extracting",
        current=page_number,
        total=0,  # Total pages unknown
        message=f"Processing page {page_number}",
        status="running"
    )
    extract_data_from_page(driver, wait)

    while True:
        try:
            check_for_hang()
            if not check_driver_health(driver):
                raise WebDriverException("Driver connection lost")

            try:
                pagination_xpath = "//tr[@class='pagination']/td/table/tbody/tr"
                pagination_row = wait.until(
                    EC.presence_of_element_located((By.XPATH, pagination_xpath)))
            except:
                print("No pagination found. Only one page exists.")
                break

            next_page_number = page_number + 1
            print(f"Looking for page {next_page_number}...")

            next_page_link = None

            try:
                next_page_link = pagination_row.find_element(
                    By.XPATH, f".//td/a[@href and contains(@href, 'Page${next_page_number}')]"
                )
                print(f"Found direct link for page {next_page_number}")
            except:
                print(
                    f"Direct link for page {next_page_number} not found in current chunk")

            if not next_page_link:
                try:
                    target_chunk_start = (
                        (next_page_number - 1) // 10) * 10 + 1
                    if target_chunk_start > next_page_number:
                        target_chunk_start -= 10

                    if target_chunk_start != 1 and target_chunk_start % 10 == 1:
                        ellipsis_link = pagination_row.find_element(
                            By.XPATH, f".//td/a[@href and contains(@href, 'Page${target_chunk_start}') and text()='...']"
                        )
                        print(
                            f"Found ellipsis link for chunk starting at page {target_chunk_start}")

                        href_value = ellipsis_link.get_attribute("href")
                        if "__doPostBack" in href_value:
                            script = href_value.split('javascript:')[1]
                            driver.execute_script(f"javascript:{script}")

                            wait.until(EC.presence_of_element_located(
                                (By.XPATH, pagination_xpath)))
                            time.sleep(1)

                            pagination_row = driver.find_element(
                                By.XPATH, pagination_xpath)
                            next_page_link = pagination_row.find_element(
                                By.XPATH, f".//td/a[@href and contains(@href, 'Page${next_page_number}')]"
                            )
                            print(
                                f"Found page {next_page_number} link after loading new chunk")

                except Exception as e:
                    print(f"Could not find ellipsis link: {e}")

            if not next_page_link:
                print(
                    f"No link found for page {next_page_number}. Reached end of pagination.")
                break

            try:
                href_value = next_page_link.get_attribute("href")
                if "__doPostBack" in href_value:
                    script = href_value.split('javascript:')[1]

                    try:
                        driver.execute_script(
                            "arguments[0].click();", next_page_link)
                    except:
                        driver.execute_script(f"javascript:{script}")

                    try:
                        WebDriverWait(driver, 10).until(
                            EC.staleness_of(pagination_row))

                        wait.until(EC.presence_of_element_located(
                            (By.XPATH,
                             "//tr[contains(@class, 'BgWhite') or contains(@class, 'BgSilver')]")
                        ))

                        time.sleep(1)

                        page_number = next_page_number
                        print(f"Successfully moved to page {page_number}")
                        print(f"Processing page {page_number}...")
                        # Update progress to show current page number
                        update_progress(
                            stage="extracting",
                            current=page_number,
                            total=0,  # Total pages unknown
                            message=f"Processing page {page_number}",
                            status="running"
                        )
                        extract_data_from_page(driver, wait)

                        # Cleanup every 5 pages
                        if page_number % 5 == 0:
                            cleanup_resources(driver)

                    except TimeoutException as te:
                        print(
                            f"Timeout while waiting for page {next_page_number} to load: {te}")
                        try:
                            current_rows = driver.find_elements(By.XPATH,
                                                                "//tr[contains(@class, 'BgWhite') or contains(@class, 'BgSilver')]")
                            if current_rows:
                                print(
                                    f"Found {len(current_rows)} rows on page, continuing...")
                                page_number = next_page_number
                                # Update progress to show current page number
                                update_progress(
                                    stage="extracting",
                                    current=page_number,
                                    total=0,  # Total pages unknown
                                    message=f"Processing page {page_number}",
                                    status="running"
                                )
                                extract_data_from_page(driver, wait)
                            else:
                                print("No rows found, assuming pagination failed")
                                break
                        except Exception as recovery_error:
                            print(f"Recovery attempt failed: {recovery_error}")
                            break

                else:
                    print(
                        f"Invalid href for page {next_page_number}: {href_value}")
                    break

            except Exception as e:
                print(f"Error clicking page {next_page_number}: {e}")
                break

        except Exception as e:
            print(f"Error during pagination at page {page_number}: {e}")
            break


@retry(max_attempts=2, delay=2, cleanup_func=cleanup_resources)
def process_nsn_links_comprehensive(driver, start_time, nsns_to_process=None,
                                    scrape_date_for_status=None, phase=None):
    """Process each unique NSN and create separate records for each CAGE+Part combination.

    If nsns_to_process is provided (list or set of NSN strings), only those NSNs are processed.
    If scrape_date_for_status and phase are provided, per-NSN status is persisted immediately.
    """
    total_rows = len(row_data_list)
    successful_saves = 0
    failed_saves = 0
    new_records_inserted = 0  # Track actual new database records
    existing_records_updated = 0  # Track updates to existing records

    # Track per-NSN status
    nsn_status = {}          # nsn -> "success" / "failed"
    nsn_failed_reasons = {}  # nsn -> reason string

    # Group rows by NSN to avoid re-processing the same NSN page
    nsn_groups = {}
    for row_data in row_data_list:
        nsn = row_data.get('nsn', 'Unknown')

        # Optional filter: only process selected NSNs in this run
        if nsns_to_process is not None and nsn not in nsns_to_process:
            continue

        if nsn not in nsn_groups:
            nsn_groups[nsn] = []
        nsn_groups[nsn].append(row_data)

    print(
        f"Processing {len(nsn_groups)} unique NSNs from {total_rows} total rows...")
    print("STRATEGY: Create separate records for each NSN+CAGE+Part combination")

    for nsn_index, (nsn, nsn_rows) in enumerate(nsn_groups.items(), 1):
        print(f"\n=== Processing NSN {nsn_index}/{len(nsn_groups)}: {nsn} ===")
        
        # Update progress
        update_progress(
            stage="processing_nsns",
            current=nsn_index,
            total=len(nsn_groups),
            message=f"Processing data {nsn_index}/{len(nsn_groups)}"
        )

        # Show all solicitations for this NSN (for information only)
        solicitations_info = []
        total_quantity_all_solicitations = 0

        for row in nsn_rows:
            raw_quantity = row.get('quantity', '0')
            quantity = extract_quantity(raw_quantity)
            total_quantity_all_solicitations += quantity
            solicitations_info.append({
                'solicitation': row.get('solicitation', 'N/A'),
                'quantity': quantity
            })

        print(f"Found {len(nsn_rows)} solicitations for this NSN:")
        for sol in solicitations_info:
            print(f"  - {sol['solicitation']}: QTY {sol['quantity']}")
        print(
            f"Total quantity across all solicitations: {total_quantity_all_solicitations}")

        # count how many records are persisted for this NSN in this run
        records_saved_for_nsn = 0

        try:
            # Use the first row to get the NSN link and other common data
            first_row = nsn_rows[0]
            nsn_link = first_row['nsn_link']

            # Navigate to NSN page ONCE
            if not safe_get(driver, nsn_link):
                print(f"SKIPPING NSN {nsn}: Failed to load NSN page - network error or page timeout")
                failed_saves += 1
                nsn_status[nsn] = "failed"
                nsn_failed_reasons[nsn] = "Failed to load NSN page: Network error, timeout, or page not accessible"
                continue

            # Extract CAGE codes and part numbers ONCE
            cage_values = []
            part_numbers = []

            try:
                cage_table = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//table[@summary='Table conatins Approved Source Data']"))
                )

                cage_rows = cage_table.find_elements(By.XPATH, ".//tbody/tr")
                print(f"Found {len(cage_rows)} CAGE codes for NSN {nsn}")

                for j, cage_row in enumerate(cage_rows, 1):
                    try:
                        cage_value = cage_row.find_element(
                            By.XPATH, "./td[@headers='h1']").text.strip()
                        part_number = cage_row.find_element(
                            By.XPATH, "./td[@headers='h2']").text.strip()
                        cage_values.append(cage_value)
                        part_numbers.append(part_number)
                        print(
                            f"  CAGE {j}: {cage_value} | Part: {part_number}")
                    except Exception as e:
                        print(f"  Error extracting CAGE row {j}: {e}")

                if not cage_values:
                    print(f"SKIPPING NSN {nsn}: No CAGE codes found - NSN page may be empty or data not available")
                    failed_saves += 1
                    nsn_status[nsn] = "failed"
                    nsn_failed_reasons[nsn] = "No CAGE codes found: NSN page structure may have changed or no approved sources available"
                    continue

            except Exception as cage_error:
                print(f"SKIPPING NSN {nsn}: Error finding CAGE table - {cage_error}")
                failed_saves += 1
                nsn_status[nsn] = "failed"
                nsn_failed_reasons[nsn] = f"CAGE table extraction error: {str(cage_error)} - Page structure may have changed or element not found"
                continue

            # Get CAGE details ONCE
            print(f"Getting CAGE details for {len(cage_values)} codes...")
            cage_details_list = extract_cage_details_comprehensive(
                driver, cage_values)

            # Extract PDF data ONCE
            print(f"[NSN {nsn}] Starting PDF extraction...")
            try:
                print(f"[NSN {nsn}] Waiting for solicitation table...")
                solicitation_table = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//table[@summary='Contains RFQ records for the NSN. ']"))
                )
                print(f"[NSN {nsn}] Solicitation table found, looking for PDF link...")

                pdf_link = WebDriverWait(solicitation_table, 60).until(
                    EC.presence_of_element_located(
                        (By.XPATH, ".//tbody/tr[1]/td[1]/a"))
                )
                pdf_url = pdf_link.get_attribute("href")
                print(f"[NSN {nsn}] PDF URL found: {pdf_url[:50]}...")

                print(f"[NSN {nsn}] Extracting PDF data (this may take a moment)...")
                unit_value, inspection_point, acceptance_point, deliver_fob, deliver_days, buyer_info, prep_for_delivery, solicitation_line_number, procurement_history, higher_level_quality_indicator = extract_unit_from_pdf_comprehensive(
                    pdf_url, driver=driver)
                print(f"[NSN {nsn}] PDF extracted - Unit: {unit_value}, Line Number: {solicitation_line_number}, Procurement History: {len(procurement_history)} records, HLQI: {higher_level_quality_indicator or '(unknown)'}")

            except TimeoutException as pdf_timeout:
                print(f"[NSN {nsn}] PDF extraction TIMEOUT: {pdf_timeout}")
                print(f"[NSN {nsn}] Continuing with empty PDF data...")
                unit_value = inspection_point = acceptance_point = deliver_fob = deliver_days = buyer_info = prep_for_delivery = solicitation_line_number = ""
                procurement_history = []
                higher_level_quality_indicator = ""
            except Exception as pdf_error:
                print(f"[NSN {nsn}] PDF extraction failed: {pdf_error}")
                print(f"[NSN {nsn}] Error type: {type(pdf_error).__name__}")
                import traceback
                print(f"[NSN {nsn}] Traceback: {traceback.format_exc()}")
                unit_value = inspection_point = acceptance_point = deliver_fob = deliver_days = buyer_info = prep_for_delivery = solicitation_line_number = ""
                procurement_history = []
                higher_level_quality_indicator = ""

            unit_code = unit_value.strip().upper() if unit_value else 'N/A'
            unit_description = UNIT_MAPPING.get(
                unit_code, f'{unit_code} (Unknown)')
            unit = f"{unit_code} ({unit_description})" if unit_code != 'N/A' else 'N/A'

            if unit == 'N/A' or unit_code == 'N/A':
                print(f"SKIPPING NSN {nsn}: Unit extraction failed - Unit is N/A after PDF extraction (regex and AI both failed)")
                failed_saves += 1
                nsn_status[nsn] = "failed"
                nsn_failed_reasons[nsn] = "Unit extraction failed: Unit is N/A after PDF extraction. Both regex patterns and AI extraction failed to find a valid unit of issue."
                continue

            # NEW LOGIC: Create records for each solicitation-CAGE-part combination
            print(f"[NSN {nsn}] Creating records for each solicitation-CAGE-part combination...")
            print(f"[NSN {nsn}] Processing {len(nsn_rows)} solicitations...")

            # Process each solicitation separately
            for solicitation_idx, solicitation_data in enumerate(nsn_rows, 1):
                solicitation = solicitation_data.get('solicitation', 'N/A')
                raw_quantity = solicitation_data.get('quantity', '0')
                solicitation_quantity = extract_quantity(raw_quantity)

                print(
                    f"[NSN {nsn}] Processing solicitation {solicitation_idx}/{len(nsn_rows)}: {solicitation} with quantity {solicitation_quantity}")

                # Create record for each CAGE+Part combination with this solicitation's quantity
                for j, cage in enumerate(cage_values):
                    print(f"[NSN {nsn}] Processing CAGE {j+1}/{len(cage_values)}: {cage}")
                    cage = cage.strip()
                    part_number = part_numbers[j].strip(
                    ) if j < len(part_numbers) else 'N/A'

                    # Create record with THIS SOLICITATION's quantity only
                    nsn_record = {
                        'NSN': nsn,
                        'Nomenclature': solicitation_data.get('nomenclature', 'N/A'),
                        # CHANGED: Use individual solicitation quantity
                        'Quantity': solicitation_quantity,
                        'Solicitation': solicitation,
                        'Status': solicitation_data.get('status', 'N/A'),
                        'Issued Date': solicitation_data.get('issued_date', 'N/A'),
                        'Return By Date': solicitation_data.get('return_by_date', 'N/A'),
                        'Purchase Request': solicitation_data.get('purchase_request', ''),  # From web table extraction
                        'Line Number': solicitation_line_number,  # From PDF extraction
                        'Procurement History': procurement_history,  # From PDF extraction
                        'CAGE Code': cage,
                        'Part Number': part_number,
                        'Unit': unit,
                        'Inspection Point': inspection_point,
                        'Acceptance Point': acceptance_point,
                        'Deliver FOB': deliver_fob,
                        'Deliver Days': deliver_days,
                        'Prep For Delivery': prep_for_delivery,
                        'Buyer Info': buyer_info,
                        'Higher Level Quality Indicator': higher_level_quality_indicator,
                    }

                    print(
                        f"  Record: SOL={solicitation}, CAGE={cage}, PART={part_number}, QTY={solicitation_quantity}")

                    # Save individual record
                    print(f"[NSN {nsn}] Saving record to database...")
                    try:
                        success, is_new = save_single_record_to_db(nsn_record, cage_details_list)
                    except Exception as db_error:
                        print(f"[NSN {nsn}] Database save exception: {db_error}")
                        import traceback
                        print(f"[NSN {nsn}] Database error traceback: {traceback.format_exc()}")
                        success = False
                        is_new = False
                    
                    if success:
                        records_saved_for_nsn += 1
                        successful_saves += 1
                        if is_new:
                            new_records_inserted += 1
                            print(f"    SUCCESS - New record inserted")
                        else:
                            existing_records_updated += 1
                            print(f"    SUCCESS - Existing record updated")
                    else:
                        failed_saves += 1
                        print(f"    FAILED - Database save failed")

            print(f"[NSN {nsn}] COMPLETE: {records_saved_for_nsn} individual records saved")
            print(f"[NSN {nsn}] Overall progress: {successful_saves} saved, {failed_saves} failed")
            
            # Update progress after each NSN
            update_progress(
                stage="processing_nsns",
                current=nsn_index,
                total=len(nsn_groups),
                message=f"Processing data {nsn_index}/{len(nsn_groups)}"
            )

            # Mark NSN status based on whether we saved any records
            if records_saved_for_nsn > 0:
                nsn_status[nsn] = "success"
            else:
                nsn_status[nsn] = "failed"
                nsn_failed_reasons[nsn] = "No records were saved for this NSN"

            # Save NSN status immediately for this NSN (per-NSN persistence)
            if scrape_date_for_status and phase:
                try:
                    save_nsn_status_batch(scrape_date_for_status, phase, {nsn: nsn_status[nsn]})
                except Exception as e:
                    print(f"Warning: failed to save NSN status for {nsn} (phase {phase}): {e}")

        except Exception as e:
            print(f"SKIPPING NSN {nsn}: Unexpected error during processing - {e}")
            failed_saves += 1
            nsn_status[nsn] = "failed"
            nsn_failed_reasons[nsn] = f"Unexpected processing error: {str(e)}"

            # Persist failed status immediately as well
            if scrape_date_for_status and phase:
                try:
                    save_nsn_status_batch(scrape_date_for_status, phase, {nsn: "failed"})
                except Exception as e2:
                    print(f"Warning: failed to save FAILED NSN status for {nsn} (phase {phase}): {e2}")

    print(f"\nFINAL RESULTS:")
    print(f"   Unique NSNs processed: {len(nsn_groups)}")
    print(f"   Original solicitation rows: {total_rows}")
    print(f"   Total database operations: {successful_saves} successful, {failed_saves} failed")
    print(f"   New records inserted: {new_records_inserted}")
    print(f"   Existing records updated: {existing_records_updated}")
    print(f"   Total unique records in database: {new_records_inserted} (updates don't create new records)")

    # Report failed NSNs for this run
    failed_nsns = [n for n, status in nsn_status.items() if status == "failed"]
    if failed_nsns:
        print("\nNSNs that failed in this run:")
        for n in failed_nsns:
            reason = nsn_failed_reasons.get(n, "unknown error")
            print(f"  - {n}: {reason}")
    else:
        print("\nAll NSNs processed successfully in this run.")

    # Return both count and detailed per-NSN status so caller can optionally retry
    return successful_saves, nsn_status, new_records_inserted, existing_records_updated


@retry(max_attempts=2, delay=3, cleanup_func=cleanup_resources)
def extract_cage_details_comprehensive(driver, cage_codes):
    """Enhanced CAGE extraction with validation and re-scraping of empty cached data"""
    unique_cages = list(set(cage_codes))
    extracted_data = []

    # Check cache first with validation for meaningful data
    cached_results = []
    uncached_cages = []

    print(f"\n180-Day Cache Status Check with Data Validation:")
    print("=" * 50)

    for cage_code in unique_cages:
        if cage_code in cage_cache:
            cached_entry = cage_cache[cage_code]

            # print(f"Cache HIT for CAGE {cage_code}")

            # VALIDATE if cached data has meaningful information
            has_meaningful_data = False

            if isinstance(cached_entry, dict):
                # Check meaningful fields for actual data (not just "N/A")
                meaningful_fields = ['Organization Name',
                                     'City', 'Phone', 'Street Name', 'Email']

                for field in meaningful_fields:
                    value = cached_entry.get(field, 'N/A')
                    if value not in ['N/A', '', None, '-']:
                        has_meaningful_data = True
                        break

                if has_meaningful_data:
                    # Print what meaningful data we found
                    org_name = cached_entry.get('Organization Name', 'N/A')
                    city = cached_entry.get('City', 'N/A')
                    phone = cached_entry.get('Phone', 'N/A')

                    print(f"VALID cached data found:")
                    print(f"Organization: {org_name}")
                    print(f"City: {city}")
                    print(f"Phone: {phone}")

                    cached_results.append(cached_entry)
                    print(f"USING cached data")
                else:
                    # Cache hit but data is empty - need to re-scrape
                    print(f"EMPTY cached data found - all fields are N/A")
                    print(f"Will re-scrape and update cache")
                    uncached_cages.append(cage_code)
            else:
                print(f"Invalid cached data format: {type(cached_entry)}")
                print(f"Will re-scrape and update cache")
                uncached_cages.append(cage_code)
        else:
            uncached_cages.append(cage_code)
            print(f"Cache MISS for CAGE {cage_code}")

    print(f"\nCache Analysis Summary:")
    print(f"Total CAGE codes to process: {len(unique_cages)}")
    print(f"Valid cached entries (with data): {len(cached_results)}")
    print(
        f"Empty/Invalid cached entries: {len(unique_cages) - len(uncached_cages) - len(cached_results)}")
    print(
        f"Never cached entries: {len(uncached_cages) - (len(unique_cages) - len(uncached_cages) - len(cached_results))}")
    print(f"Total need to fetch from web: {len(uncached_cages)}")
    print(
        f"Useful cache efficiency: {(len(cached_results)/len(unique_cages)*100):.1f}%")
    print("=" * 50)

    # Process uncached CAGE codes (including empty cached ones)
    for i, cage_code in enumerate(uncached_cages, 1):
        # Track whether this CAGE had a (possibly empty) cached entry before re-scraping
        was_cached = cage_code in cage_cache
        cage_data = {
            "CAGE Code": cage_code,
            "Organization Name": "N/A",
            "Street Name": "N/A",
            "City": "N/A",
            "Postal Code": "N/A",
            "Phone": "N/A",
            "Fax": "N/A",
            "Email": "N/A"
        }

        extraction_successful = False

        try:
            check_for_hang()
            if not check_driver_health(driver):
                print(f"Driver health check failed for CAGE {cage_code}")
                # Update cache even with empty data to avoid re-attempting immediately
                cage_cache[cage_code] = cage_data
                extracted_data.append(cage_data)
                continue

            # Check if this was previously cached (empty) or completely new
            was_cached = cage_code in cage_cache
            print(
                f"Processing CAGE code {i}/{len(uncached_cages)}: {cage_code} {'(re-scraping empty cache)' if was_cached else '(new)'}")

            # Navigate directly to CAGE details page (skips search form and expand click)
            cage_view_url = f"https://eportal.nspa.nato.int/Codification/CageTool/cage-view/{cage_code}"
            driver.set_page_load_timeout(30)

            if not safe_get(driver, cage_view_url):
                print(f"Failed to load CAGE details page for {cage_code}")
                cage_cache[cage_code] = cage_data
                extracted_data.append(cage_data)
                continue

            # Wait for page to fully load
            WebDriverWait(driver, 30).until(
                lambda d: d.execute_script(
                    'return document.readyState') == 'complete'
            )
            time.sleep(3)  # Wait for Angular/content to load

            try:
                # Check if CAGE was not found (direct view may show rejection or no-data message)
                no_data_messages = driver.find_elements(
                    By.XPATH, "//*[contains(text(), 'No data') or contains(text(), 'not found') or contains(text(), 'No records') or contains(text(), 'Request Rejected')]")
                if no_data_messages:
                    print(f"CAGE {cage_code} not found or page rejected")
                    cage_cache[cage_code] = cage_data
                    extracted_data.append(cage_data)
                    continue

                # Extract data using comprehensive approach (details page is already open)
                try:
                    # Try multiple strategies to find the data
                    read_only_elements = driver.find_elements(
                        By.CSS_SELECTOR, "div.ng-star-inserted > span.readOnly")
                    if not read_only_elements:
                        read_only_elements = driver.find_elements(
                            By.CSS_SELECTOR, "span.readOnly")
                        if not read_only_elements:
                            read_only_elements = driver.find_elements(
                                By.CSS_SELECTOR, ".readOnly")

                    phone_fax = driver.find_elements(
                        By.CSS_SELECTOR, "div.ng-star-inserted > div.ng-star-inserted > span")
                    if not phone_fax:
                        phone_fax = driver.find_elements(
                            By.CSS_SELECTOR, "span")

                    print(
                        f"Found {len(read_only_elements)} readonly elements for CAGE {cage_code}")

                    # Extract organization name
                    if len(read_only_elements) > 1:
                        org_name = read_only_elements[1].text.strip()
                        if org_name and org_name != 'N/A':
                            cage_data["Organization Name"] = org_name

                    # Extract street name
                    if len(read_only_elements) > 10:
                        street = read_only_elements[10].text.strip()
                        if street and street != 'N/A':
                            cage_data["Street Name"] = street

                    # Extract city
                    if len(read_only_elements) > 12:
                        city = read_only_elements[12].text.strip()
                        if city and city != 'N/A':
                            cage_data["City"] = city

                    # Extract postal code
                    if len(read_only_elements) > 13:
                        postal = read_only_elements[13].text.strip()
                        if postal and postal != 'N/A':
                            cage_data["Postal Code"] = postal

                    # Extract phone
                    if len(phone_fax) > 0:
                        phone = phone_fax[0].text.strip()
                        if phone and phone != 'N/A':
                            cage_data["Phone"] = phone

                    # Extract fax with error handling
                    try:
                        fax_element = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located(
                                (By.XPATH, "//label[contains(text(), 'Fax(es)')]/following-sibling::div"))
                        )
                        fax = fax_element.text.strip()
                        if fax and fax != 'N/A':
                            cage_data["Fax"] = fax
                    except:
                        pass

                    # Extract email with error handling
                    try:
                        email_element = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "a[href^='mailto:']"))
                        )
                        email = email_element.get_attribute(
                            "href").replace("mailto:", "").strip()
                        if email and email != 'N/A':
                            cage_data["Email"] = email
                    except:
                        # Try to find any email-like text
                        email_elements = driver.find_elements(
                            By.XPATH, "//*[contains(text(), '@')]")
                        if email_elements:
                            for elem in email_elements:
                                text = elem.text.strip()
                                if '@' in text and '.' in text and text != 'N/A':
                                    cage_data["Email"] = text
                                    break

                    # Validate extraction success
                    meaningful_fields = ['Organization Name',
                                         'City', 'Phone', 'Street Name', 'Email']
                    extracted_fields = [field for field in meaningful_fields if cage_data.get(
                        field, 'N/A') not in ['N/A', '', None]]

                    if extracted_fields:
                        extraction_successful = True
                        print(
                            f"Successfully extracted data for CAGE {cage_code}:")
                        for field in extracted_fields:
                            print(f"   {field}: {cage_data[field]}")
                    else:
                        print(
                            f"Extraction failed for CAGE {cage_code} - no meaningful data found")

                except Exception as data_extraction_error:
                    print(
                        f"Error extracting data fields for CAGE {cage_code}: {data_extraction_error}")

            except TimeoutException as te:
                print(f"Timeout while processing CAGE {cage_code}: {te}")
            except Exception as processing_error:
                print(
                    f"Error during CAGE processing for {cage_code}: {processing_error}")

        except Exception as e:
            print(f"Error extracting data for CAGE code {cage_code}: {e}")

        # Always update cache with new data (even if still empty)
        if was_cached:
            print(
                f"Updating cache for CAGE {cage_code} (was previously empty)")
        else:
            print(f"Adding CAGE {cage_code} to cache for 180 days")

        cage_cache[cage_code] = cage_data
        extracted_data.append(cage_data)

        # Add small delay between requests to be respectful
        time.sleep(1)

    # Add cached results to final output
    extracted_data.extend(cached_results)

    # Save updated cache to file
    print(f"\nSaving updated cache...")
    save_cage_cache(cage_cache)

    print(f"\nCage extraction complete:")
    print(f"Total results: {len(extracted_data)}")
    print(f"New/Updated entries: {len(uncached_cages)}")
    print(f"Valid cached entries used: {len(cached_results)}")
    print(
        f"Overall success rate: {(len([d for d in extracted_data if d.get('Organization Name', 'N/A') != 'N/A'])/len(extracted_data)*100):.1f}%")

    return extracted_data


def consolidate_duplicates(nsn_data_list):
    """Consolidate records with the same CAGE code, nomenclature, NSN, return_by_date, and part number (ignoring solicitation)"""
    print("Starting consolidation process...")

    consolidated_dict = defaultdict(list)

    for record in nsn_data_list:
        consolidation_key = (
            record.get('CAGE Code', '').strip(),
            record.get('Nomenclature', '').strip(),
            record.get('NSN', '').strip(),
            record.get('Return By Date', '').strip(),
            record.get('Part Number', '').strip()
            # REMOVED: Solicitation from consolidation key - now different solicitations with same NSN+CAGE+Part will be consolidated
        )
        consolidated_dict[consolidation_key].append(record)

    consolidated_list = []

    for key, records in consolidated_dict.items():
        if len(records) == 1:
            # Single record - no consolidation needed
            consolidated_list.append(records[0])
        else:
            # Multiple records with same key - consolidate them
            cage_code, nomenclature, nsn, return_by_date, part_number = key
            print(
                f"Consolidating {len(records)} records for CAGE: {cage_code}, NSN: {nsn}, Part: {part_number}")

            # Use first record as base and sum quantities
            base_record = records[0].copy()
            total_quantity = 0
            all_solicitations = set()

            for record in records:
                # Sum quantities from different solicitations
                quantity = record.get('Quantity', 0)
                if quantity is not None and isinstance(quantity, (int, float)):
                    total_quantity += quantity
                elif quantity is not None:
                    try:
                        total_quantity += int(quantity)
                    except (ValueError, TypeError):
                        print(
                            f"Warning: Could not convert quantity '{quantity}' to number")

                # Collect all solicitation numbers for audit trail
                solicitation = record.get('Solicitation', '').strip()
                if solicitation and solicitation != 'N/A':
                    all_solicitations.add(solicitation)

            # Update the base record with consolidated data
            base_record['Quantity'] = total_quantity

            # Keep the part number from the key (should be same for all records in this group)
            base_record['Part Number'] = part_number if part_number and part_number != 'N/A' else 'N/A'

            # Store primary solicitation number only
            if all_solicitations:
                # Keep the first solicitation as primary
                base_record['Solicitation'] = sorted(all_solicitations)[
                    0]  # Use first solicitation as primary
                print(
                    f"  Using primary solicitation: {base_record['Solicitation']}")
                if len(all_solicitations) > 1:
                    print(
                        f"  (Consolidated from {len(all_solicitations)} solicitations)")

            consolidated_list.append(base_record)
            print(f"  Result: 1 record with total quantity: {total_quantity}")

    print(
        f"Consolidation complete: {len(nsn_data_list)} -> {len(consolidated_list)} records")
    return consolidated_list


def process_row_data(row_data_list):
    """Process row data and create NSN entries"""
    temp_nsn_data_list = []

    print("Processing row data...")

    for row_data in row_data_list:
        try:
            check_for_hang()
            nsn = row_data.get('nsn', 'N/A')
            nomenclature = row_data.get('nomenclature', 'N/A')
            solicitation = row_data.get('solicitation', 'N/A')
            status = row_data.get('status', 'N/A')
            issued_date = row_data.get('issued_date', 'N/A')
            return_by_date = row_data.get('return_by_date', 'N/A')

            unit_code = row_data.get('unit', 'N/A').strip().upper()
            unit_description = UNIT_MAPPING.get(
                unit_code, f'{unit_code} (Unknown)')
            unit = f"{unit_code} ({unit_description})" if unit_code != 'N/A' else 'N/A'

            inspection_point = row_data.get('inspection_point', '')
            acceptance_point = row_data.get('acceptance_point', '')
            deliver_fob = row_data.get('deliver_fob', '')
            deliver_days = row_data.get('deliver_days', '')
            prep_for_delivery = row_data.get('prep_for_delivery', '')
            buyer_info = row_data.get('buyer_info', '')

            raw_quantity = row_data.get('quantity', '0')
            quantity = extract_quantity(raw_quantity)

            cage_values = row_data.get('cages', '-').split(', ')
            part_numbers = row_data.get('part_numbers', '-').split(', ')

            while len(part_numbers) < len(cage_values):
                part_numbers.append('N/A')

            for i, cage in enumerate(cage_values):
                cage = cage.strip()
                part_number = part_numbers[i].strip(
                ) if i < len(part_numbers) else 'N/A'

                nsn_entry = {
                    'NSN': nsn,
                    'Nomenclature': nomenclature,
                    'Quantity': quantity,
                    'Solicitation': solicitation,
                    'Status': status,
                    'Issued Date': issued_date,
                    'Return By Date': return_by_date,
                    'CAGE Code': cage if cage else 'N/A',
                    'Part Number': part_number if part_number else 'N/A',
                    'Unit': unit,
                    'Inspection Point': inspection_point,
                    'Acceptance Point': acceptance_point,
                    'Deliver FOB': deliver_fob,
                    'Deliver Days': deliver_days,
                    'Prep For Delivery': prep_for_delivery,
                    'Buyer Info': buyer_info
                }
                temp_nsn_data_list.append(nsn_entry)

        except Exception as e:
            print(f"Error processing row data: {e}")

    consolidated_data = consolidate_duplicates(temp_nsn_data_list)
    return consolidated_data


def save_single_record_to_db(record_data, cage_details_list):
    """Save record to database or update quantity if it already exists.
       Identity = (NSN, CAGE, PART_NUMBER, RETURN_BY_DATE). Solicitation is metadata only.
    """
    nsn = record_data.get('NSN', 'N/A')
    solicitation = record_data.get('Solicitation', 'N/A')
    cage_code = record_data.get('CAGE Code', 'N/A')
    part_number = record_data.get('Part Number', 'N/A')
    return_by = record_data.get('Return By Date', 'N/A')

    # coerce quantity to int safely
    new_quantity = record_data.get('Quantity') or 0
    try:
        new_quantity = int(new_quantity)
    except Exception:
        new_quantity = 0

    # check existing by nsn+cage+part+return_by
    existing_quantity = get_existing_nsn_quantity(
        nsn, cage_code, part_number, return_by)

    if existing_quantity is not None:
        print(
            f"  UPDATING EXISTING: NSN={nsn}, CAGE={cage_code}, PART={part_number}, RETURN_BY={return_by}")
        print(
            f"  Current quantity: {existing_quantity}, Adding: {new_quantity}")
        success = update_existing_quantity(
            nsn, cage_code, part_number, return_by, new_quantity)
        if success:
            try:
                print(
                    f"  SUCCESS: Total quantity now: {int(existing_quantity) + int(new_quantity)}")
            except Exception:
                print("  SUCCESS: Quantity updated")
            return True, False  # Success, but not a new record (it's an update)
        else:
            print("  FAILED: Could not update quantity")
            return False, False

    # ========================
    # INSERT NEW RECORD
    # ========================
    print(
        f"  INSERTING NEW: NSN={nsn}, CAGE={cage_code}, PART={part_number}, RETURN_BY={return_by}, QTY={new_quantity}")

    sql_query = """
    INSERT INTO solicitations_solicitation
    (cage, nsn, nomenclature, solicitation, status, quantity, issued_date, return_by_date,
     organization_name, street_name, city, postal_code, phone, fax, email, part_number, unit,
     inspection_point, acceptance_point, deliver_fob, deliver_days, buyer_info, prep_for_delivery, scraped_date, solicitation_line_number, procurement_history, purchase_request_number, is_set_aside, higher_level_quality_indicator)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    try:
        db_connection = MySQLdb.connect(
            host=DB_HOST,
            user=DB_USER,
            passwd=DB_PASSWORD,
            db=DB_NAME,
            port=DB_PORT,
            cursorclass=DictCursor,
            autocommit=True
        )
        cursor = db_connection.cursor()

        # attach CAGE details if available
        cage_details = next(
            (item for item in cage_details_list if item['CAGE Code'] == cage_code), None)

        if cage_details:
            organization_name = cage_details.get('Organization Name', 'N/A')
            street_name = cage_details.get('Street Name', 'N/A')
            city = cage_details.get('City', 'N/A')
            postal_code = cage_details.get('Postal Code', 'N/A')
            phone = cage_details.get('Phone', 'N/A')
            fax = cage_details.get('Fax', 'N/A')
            email = cage_details.get('Email', 'N/A')
        else:
            organization_name = street_name = city = postal_code = phone = fax = email = 'N/A'

        # Convert procurement_history list to JSON string for MySQL JSON field
        procurement_history_data = record_data.get('Procurement History', [])
        procurement_history_json = json.dumps(procurement_history_data) if procurement_history_data else '[]'
        
        db_record = (
            cage_code, nsn, record_data.get(
                'Nomenclature', 'N/A'), solicitation,
            record_data.get(
                'Status', 'N/A'), new_quantity, record_data.get('Issued Date', 'N/A'),
            return_by, organization_name, street_name, city, postal_code, phone, fax, email,
            part_number, record_data.get('Unit', 'EA (EACH)'),
            record_data.get('Inspection Point', ''), record_data.get(
                'Acceptance Point', ''),
            record_data.get('Deliver FOB', ''), record_data.get(
                'Deliver Days', ''),
            record_data.get('Buyer Info', ''),
            record_data.get('Prep For Delivery', ''),
            datetime.date.today(),
            record_data.get('Line Number', ''),
            procurement_history_json,
            record_data.get('Purchase Request', ''),
            True,  # is_set_aside - default to True as per model
            record_data.get('Higher Level Quality Indicator', ''),
        )

        cursor.execute(sql_query, db_record)
        print(f"  SUCCESS: New record inserted with quantity {new_quantity}")
        return True, True  # Success, and it's a new record

    except Exception as e:
        print(f"  Error inserting new record: {e}")
        return False, False
    finally:
        try:
            if 'db_connection' in locals():
                db_connection.close()
        except:
            pass


def get_existing_nsn_quantity(nsn, cage_code, part_number, return_by_date):
    """Get existing quantity for NSN+CAGE+PART+RETURN_BY combination (solicitation-agnostic)."""
    check_query = """
    SELECT quantity 
    FROM solicitations_solicitation 
    WHERE nsn = %s AND cage = %s AND part_number = %s AND return_by_date = %s
    LIMIT 1
    """
    try:
        db_connection = MySQLdb.connect(
            host=DB_HOST,
            user=DB_USER,
            passwd=DB_PASSWORD,
            db=DB_NAME,
            port=DB_PORT,
            cursorclass=DictCursor
        )
        cursor = db_connection.cursor()
        cursor.execute(check_query, (nsn, cage_code,
                       part_number, return_by_date))
        result = cursor.fetchone()
        if result:
            try:
                existing_quantity = int(result['quantity'] or 0)
            except Exception:
                existing_quantity = 0
            print(
                f"  EXISTING RECORD: (NSN={nsn}, CAGE={cage_code}, PART={part_number}, RETURN_BY={return_by_date}) qty={existing_quantity}")
            return existing_quantity
        else:
            print(
                f"  NEW RECORD: (NSN={nsn}, CAGE={cage_code}, PART={part_number}, RETURN_BY={return_by_date}) not found")
            return None
    except Exception as e:
        print(f"  Error checking existing quantity: {e}")
        return None
    finally:
        try:
            if 'db_connection' in locals():
                db_connection.close()
        except:
            pass


def update_existing_quantity(nsn, cage_code, part_number, return_by_date, additional_quantity):
    """Update existing record (NSN+CAGE+PART+RETURN_BY) by adding new quantity."""
    update_query = """
    UPDATE solicitations_solicitation 
    SET quantity = COALESCE(quantity,0) + %s,
        scraped_date = %s
    WHERE nsn = %s AND cage = %s AND part_number = %s AND return_by_date = %s
    """
    try:
        db_connection = MySQLdb.connect(
            host=DB_HOST,
            user=DB_USER,
            passwd=DB_PASSWORD,
            db=DB_NAME,
            port=DB_PORT,
            cursorclass=DictCursor,
            autocommit=True
        )
        cursor = db_connection.cursor()

        try:
            add_qty = int(additional_quantity or 0)
        except Exception:
            add_qty = 0

        cursor.execute(update_query, (add_qty, datetime.date.today(),
                       nsn, cage_code, part_number, return_by_date))
        if cursor.rowcount > 0:
            print(
                f"  QUANTITY UPDATED: +{add_qty} for (NSN={nsn}, CAGE={cage_code}, PART={part_number}, RETURN_BY={return_by_date})")
            return True
        else:
            print("  UPDATE FAILED: No rows matched")
            return False
    except Exception as e:
        print(f"  Error updating quantity: {e}")
        return False
    finally:
        try:
            if 'db_connection' in locals():
                db_connection.close()
        except:
            pass


def save_nsn_status_batch(scrape_date, phase, nsn_status):
    """
    Persist per-NSN status for a given scrape_date and phase (1=first, 2=second).

    This writes directly to the Django DB using the same MySQL connection
    parameters as the main solicitation table.
    """
    if not scrape_date or not nsn_status:
        return

    print(f"Saving NSN status batch for date={scrape_date}, phase={phase}, count={len(nsn_status)}")

    insert_query = """
    INSERT INTO solicitations_scrapensnstatus (scrape_date, nsn, phase, status, created_at)
    VALUES (%s, %s, %s, %s, NOW())
    ON DUPLICATE KEY UPDATE status = VALUES(status), created_at = VALUES(created_at)
    """
    try:
        db_connection = MySQLdb.connect(
            host=DB_HOST,
            user=DB_USER,
            passwd=DB_PASSWORD,
            db=DB_NAME,
            port=DB_PORT,
            cursorclass=DictCursor,
            autocommit=True
        )
        cursor = db_connection.cursor()

        params = []
        for nsn, status in nsn_status.items():
            if not nsn:
                continue
            if status not in ("success", "failed"):
                continue
            params.append((scrape_date, nsn, phase, status))

        if params:
            cursor.executemany(insert_query, params)
            print(f"Saved {len(params)} NSN status rows for phase {phase}")
        else:
            print("No valid NSN statuses to save.")
    except Exception as e:
        print(f"Error saving NSN status batch: {e}")
    finally:
        try:
            if 'db_connection' in locals():
                db_connection.close()
        except:
            pass


def load_first_phase_status(scrape_date):
    """
    Load NSN status for first scraping phase (phase=1) for a given date.

    Returns two sets: (success_nsns, failed_nsns)
    """
    success_nsns = set()
    failed_nsns = set()

    if not scrape_date:
        return success_nsns, failed_nsns

    print(f"Loading first-phase NSN status for date={scrape_date}")

    select_query = """
    SELECT nsn, status
    FROM solicitations_scrapensnstatus
    WHERE scrape_date = %s AND phase = 1
    """
    try:
        db_connection = MySQLdb.connect(
            host=DB_HOST,
            user=DB_USER,
            passwd=DB_PASSWORD,
            db=DB_NAME,
            port=DB_PORT,
            cursorclass=DictCursor
        )
        cursor = db_connection.cursor()
        cursor.execute(select_query, (scrape_date,))
        rows = cursor.fetchall() or []
        for row in rows:
            nsn = (row.get("nsn") or "").strip()
            status = row.get("status")
            if not nsn or not status:
                continue
            if status == "success":
                success_nsns.add(nsn)
            elif status == "failed":
                failed_nsns.add(nsn)

        print(f"Loaded {len(success_nsns)} success and {len(failed_nsns)} failed NSNs from first phase")
    except Exception as e:
        print(f"Error loading first-phase status: {e}")
    finally:
        try:
            if 'db_connection' in locals():
                db_connection.close()
        except:
            pass

    return success_nsns, failed_nsns


def main():
    start_time = time.time()
    max_retries = 2
    retry_count = 0
    driver = None
    
    # Clear any old progress file and initialize fresh progress tracking
    clear_progress()
    update_progress(
        stage="starting",
        current=0,
        total=1,
        message="Initializing scraping process...",
        status="running"
    )

    # Display cache information at startup
    print("="*80)
    print("COMPREHENSIVE WEB SCRAPER WITH 180-DAY CAGE CACHE SYSTEM")
    print("="*80)
    print(get_cache_info())
    print("="*80)

    while retry_count < max_retries:
        try:
            driver = initialize_driver()
            if not driver:
                print("Failed to initialize WebDriver. Exiting.")
                # Update progress and cleanup before returning
                update_progress(
                    stage="failed",
                    current=0,
                    total=0,
                    message="Failed to initialize WebDriver",
                    status="failed"
                )
                time.sleep(1)
                clear_progress()
                return

            # Navigate to website with SSL error handling
            if not safe_get(driver, WEBSITE_URL):
                print("Failed to load website after multiple attempts")
                # Cleanup before returning
                try:
                    if driver:
                        driver.quit()
                        driver = None
                except:
                    pass
                update_progress(
                    stage="failed",
                    current=0,
                    total=0,
                    message="Failed to load website",
                    status="failed"
                )
                time.sleep(1)
                clear_progress()
                return

            print('=' * 70)
            print("WELCOME TO COMPREHENSIVE RFQ AUTOMATED PROGRAM")
            print('=' * 70)

            # Handle date and phase arguments
            formated_date = sys.argv[1] if len(sys.argv) > 1 else None
            phase_arg = sys.argv[2] if len(sys.argv) > 2 else "first"
            phase_arg = (phase_arg or "first").strip().lower()
            if phase_arg not in ("first", "second"):
                phase_arg = "first"

            print(
                f"Requested date: {formated_date}" if formated_date else "No date specified - will use first available date")
            print(f"Scraping phase: {phase_arg}")

            wait = WebDriverWait(driver, 30)

            # Accept terms and navigate
            click_element(wait, "butAgree")
            click_element(wait, "ctl00_cph1_lnkRfqDatesIssue")

            # Date selection logic - MODIFIED TO USE RFQ DATES TABLE
            # Wait for the date table to load
            date_table_xpath = "//table[@id='ctl00_cph1_dtlDateList' and @title='Table contains Issue Dates for RFQs']"
            date_table = wait.until(
                EC.presence_of_element_located((By.XPATH, date_table_xpath)))

            # Get all date links from the table
            date_links = date_table.find_elements(
                By.XPATH, ".//td/span/a[contains(@href, 'Value=')]")

            if date_links:
                # Extract available dates and their elements
                available_dates = []
                date_elements = {}

                for link in date_links:
                    date_text = link.text.strip()
                    available_dates.append(date_text)
                    date_elements[date_text] = link

                print(f"Found {len(available_dates)} available dates")
                first_available_date = available_dates[0] if available_dates else None
                print(f"First available date: {first_available_date}")

                # Date selection logic
                if formated_date:
                    if formated_date in date_elements:
                        target_link = date_elements[formated_date]
                        date_to_send = formated_date
                        print(f"Found requested date: {formated_date}")
                    else:
                        print(
                            f"Requested date '{formated_date}' not found in available dates")
                        print("Available dates:")
                        for date in available_dates:
                            print(f"  - {date}")
                        print(
                            f"Defaulting to first available date: {first_available_date}")
                        target_link = date_elements[first_available_date]
                        date_to_send = first_available_date
                else:
                    target_link = date_elements[first_available_date]
                    date_to_send = first_available_date
                    print(f"Using first available date: {date_to_send}")

                if target_link:
                    print(f"Clicking date link for: {date_to_send}")
                    target_link.click()
                    time.sleep(2)

                    # Send date to Django API (optional)
                    try:
                        response = requests.post(
                            'http://localhost:8000/solicitations/',
                            json={
                                'selected_date': date_to_send,
                                'is_user_input': bool(formated_date)
                            },
                            headers={'Content-Type': 'application/json'},
                            timeout=5
                        )
                        if response.status_code == 200:
                            print(
                                f"Successfully sent date to Django: {date_to_send}")
                        else:
                            print(
                                f"Django API responded with status {response.status_code} (continuing anyway)")
                    except requests.exceptions.RequestException as e:
                        print(f"Django API error (continuing anyway): {e}")
                else:
                    print("No valid date link found")
                    # Cleanup before returning
                    try:
                        if driver:
                            driver.quit()
                            driver = None
                    except:
                        pass
                    update_progress(
                        stage="failed",
                        current=0,
                        total=0,
                        message="No valid date link found",
                        status="failed"
                    )
                    time.sleep(1)
                    clear_progress()
                    return
            else:
                print("No date links found in the RFQ dates table")
                # Cleanup before returning
                try:
                    if driver:
                        driver.quit()
                        driver = None
                except:
                    pass
                update_progress(
                    stage="failed",
                    current=0,
                    total=0,
                    message="No date links found",
                    status="failed"
                )
                time.sleep(1)
                clear_progress()
                return

            # Determine scrape_date_for_status for NSN status logging.
            # Prefer the explicit CLI date (formated_date) if provided, fall back to the
            # date text we clicked in the RFQ dates table.
            scrape_date_for_status = None
            cli_date = formated_date if 'formated_date' in locals() else None
            if cli_date:
                scrape_date_for_status = parse_scrape_date(cli_date)
            if not scrape_date_for_status and date_to_send:
                scrape_date_for_status = parse_scrape_date(date_to_send)
            if scrape_date_for_status:
                print(f"NSN status will be logged for scrape_date={scrape_date_for_status}")
            else:
                print("Warning: scrape_date_for_status is None - NSN status will not be persisted for this run.")

            # Main scraping workflow
            print("Starting comprehensive data extraction...")

            # Check for pagination and handle accordingly
            if check_if_single_page(driver):
                print("Single page detected, extracting data from single page...")
                # Update progress for single page - use current=1, total=0 to indicate we're on page 1 but don't know total records yet
                update_progress(
                    stage="extracting",
                    current=1,
                    total=0,  # Unknown total records at this point
                    message="Processing page 1",
                    status="running"
                )
                try:
                    extract_data_from_page(driver, wait)
                except Exception as e:
                    print(f"Error extracting data from single page: {e}")
                    traceback.print_exc()
                    raise  # Re-raise to be caught by main exception handler
            else:
                print("Multiple pages detected, starting pagination...")
                handle_pagination(driver, wait)

            print(
                f"Total records extracted from all pages: {len(row_data_list)}")
            
            # Update progress to indicate pagination is complete, moving to NSN processing
            # Only update if we have records, otherwise the check below will handle it
            if row_data_list:
                update_progress(
                    stage="extracting",
                    current=len(row_data_list),
                    total=len(row_data_list),
                    message=f"Completed extracting {len(row_data_list)} records from all pages. Processing NSNs...",
                    status="running"
                )

            if not row_data_list:
                print("No data extracted. Exiting.")
                # Cleanup before returning
                try:
                    if driver:
                        driver.quit()
                        driver = None
                except:
                    pass
                update_progress(
                    stage="failed",
                    current=0,
                    total=0,
                    message="No data extracted from pages",
                    status="failed"
                )
                time.sleep(1)
                clear_progress()
                return

            # Decide which NSNs to process based on phase and first-phase status.
            nsns_to_process_for_phase = None

            if phase_arg == "second":
                # SECOND SCRAPING:
                # 1) Discover all NSNs currently present for this date from row_data_list
                current_nsns = set()
                for row in row_data_list:
                    nsn_val = (row.get("nsn") or "").strip()
                    if nsn_val:
                        current_nsns.add(nsn_val)

                print(f"[SECOND PHASE] Discovered {len(current_nsns)} NSNs from current RFQ table.")

                # 2) Load first-phase status for this date
                success_first, failed_first = load_first_phase_status(scrape_date_for_status)

                # 3) Compute new and retry NSNs
                already_seen_first = success_first.union(failed_first)
                new_nsns = current_nsns.difference(already_seen_first)
                retry_nsns = failed_first.intersection(current_nsns)

                nsns_to_process_for_phase = new_nsns.union(retry_nsns)

                print(f"[SECOND PHASE] First-phase success NSNs: {len(success_first)}")
                print(f"[SECOND PHASE] First-phase failed NSNs: {len(failed_first)}")
                print(f"[SECOND PHASE] New NSNs since first phase: {len(new_nsns)}")
                print(f"[SECOND PHASE] Retry NSNs (failed & still present): {len(retry_nsns)}")
                print(f"[SECOND PHASE] Total NSNs to process in second phase: {len(nsns_to_process_for_phase)}")

                if not nsns_to_process_for_phase:
                    print("[SECOND PHASE] No NSNs to process (all succeeded previously and no new NSNs).")

            # Determine numeric phase once for this run
            current_phase_number = 1 if phase_arg == "first" else 2

            # Process NSN links and save each record immediately (first pass within this script run)
            print("Processing NSN links and saving each record immediately (first pass)...")
            total_saved_first, nsn_status_first, new_records_first, updated_records_first = process_nsn_links_comprehensive(
                driver,
                start_time,
                nsns_to_process=nsns_to_process_for_phase,
                scrape_date_for_status=scrape_date_for_status,
                phase=current_phase_number,
            )

            print(
                f"First pass completed: {total_saved_first} records saved to database")

            # Persist NSN status for this phase (phase 1 or 2) in batch as a safety net
            if scrape_date_for_status and nsn_status_first:
                try:
                    save_nsn_status_batch(scrape_date_for_status, current_phase_number, nsn_status_first)
                except Exception as e:
                    print(f"Warning: failed to save NSN status batch for phase {current_phase_number}: {e}")

            # Determine which NSNs failed in the first pass
            failed_nsns_first = [
                nsn for nsn, status in nsn_status_first.items() if status == "failed"
            ]

            total_saved_second = 0
            nsn_status_second = {}
            new_records_second = 0
            updated_records_second = 0

            # Optional internal second pass: retry only failed NSNs once more (second phase only; first phase runs once)
            if current_phase_number == 2 and failed_nsns_first:
                print("\nStarting second pass to retry failed NSNs (within second phase)...")
                print("NSNs to retry:")
                for nsn in failed_nsns_first:
                    print(f"  - {nsn}")

                total_saved_second, nsn_status_second, new_records_second, updated_records_second = process_nsn_links_comprehensive(
                    driver,
                    start_time,
                    nsns_to_process=set(failed_nsns_first),
                    scrape_date_for_status=scrape_date_for_status,
                    phase=current_phase_number,
                )

                print(
                    f"Second pass completed: {total_saved_second} additional records saved to database"
                )
            elif failed_nsns_first:
                print("\nFirst phase: skipping retry pass (first phase runs only once).")
            else:
                print("\nNo NSNs failed in first pass; skipping second pass.")

            overall_saved = total_saved_first + total_saved_second
            total_new_records = new_records_first + new_records_second
            total_updated_records = updated_records_first + updated_records_second

            end_time = time.time()
            total_time = end_time - start_time
            
            print(f"Completed: {overall_saved} database operations completed")
            print(f"  - New records inserted: {total_new_records}")
            print(f"  - Existing records updated: {total_updated_records}")
            print(f"  - Total unique records in database: {total_new_records} (updates don't create new records)")
            print(
                f"Script completed successfully in {total_time/60:.2f} minutes ({total_time:.2f} seconds)")
            print(f"Processed {len(row_data_list)} total records")
            print(
                f"Average time per record: {total_time/len(row_data_list):.2f} seconds" if row_data_list else "No records processed")

            # Performance summary with cache statistics
            print("\n" + "="*60)
            print("PERFORMANCE SUMMARY:")
            print(f"Processed {len(row_data_list)} total records")
            print(f"Database operations: {overall_saved} successful ({total_new_records} new inserts, {total_updated_records} updates)")
            print(f"Total unique records in database: {total_new_records}")
            print(
                f"Average time per record: {total_time/len(row_data_list):.2f} seconds" if row_data_list else "No records processed")

            print(f"Cache file location: {CACHE_FILE_PATH}")
            print(f"Cache duration: {CACHE_DURATION_DAYS} days")
            print("="*60)

            # Update progress - completed
            update_progress(
                stage="completed",
                current=overall_saved,
                total=overall_saved,
                message=f"Scraping completed successfully! {total_new_records} new records inserted, {total_updated_records} existing records updated",
                status="completed"
            )
            
            # Wait a moment for the progress to be read, then clear it
            time.sleep(2)
            clear_progress()
            
            # Clean up driver BEFORE exiting
            try:
                if driver:
                    driver.quit()
                    driver = None
                    print("WebDriver closed successfully")
            except Exception as e:
                print(f"Error closing WebDriver: {e}")
            
            # Explicitly exit to close the background process immediately
            print("Script execution completed. Exiting.")
            sys.exit(0)

        except Exception as e:
            retry_count += 1
            print(f"Attempt {retry_count} failed: {str(e)}")
            traceback.print_exc()
            if retry_count >= max_retries:
                print("Max retries reached. Exiting.")
                # Update progress to failed and clear after delay
                update_progress(
                    stage="failed",
                    current=0,
                    total=0,
                    message="Scraping failed after maximum retries",
                    status="failed"
                )
                time.sleep(2)
                clear_progress()
                
                # Clean up driver before exiting
                try:
                    if driver:
                        driver.quit()
                        driver = None
                        print("WebDriver closed successfully")
                except Exception as e:
                    print(f"Error closing WebDriver: {e}")
                
                break
            time.sleep(5)
            # Close driver on retry to free resources
            try:
                if driver:
                    driver.quit()
                    driver = None
            except:
                pass
    
    # Final cleanup - ensure driver is closed when script exits
    try:
        if driver:
            driver.quit()
            print("WebDriver closed successfully")
    except Exception as e:
        print(f"Error closing WebDriver: {e}")
    
    # Clear progress file on exit (in case script exits without completing)
    clear_progress()
    
    print("Script execution completed. Exiting.")


if __name__ == "__main__":
    print("="*80)
    print("COMPREHENSIVE WEB SCRAPER WITH 180-DAY CAGE CACHE SYSTEM")
    print("Expected Performance: High-speed processing with comprehensive data")
    print("Key Features:")
    print("Complete PDF data extraction (unit, buyer info, delivery details)")
    print("180-day CAGE code caching system for maximum efficiency")
    print("Comprehensive CAGE code processing")
    print("Optimized single-window navigation")
    print("Enhanced error handling and recovery")
    print("Memory management and intelligent caching")
    print("Data consolidation and deduplication")
    print("Persistent cache with automatic expiration")
    print(f"Cache file: {CACHE_FILE_PATH}")
    print(f"Cache duration: {CACHE_DURATION_DAYS} days")
    print("="*80)
    main()
