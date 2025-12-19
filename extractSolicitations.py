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

# Set up Django environment
sys.path.append('D:/projects/GilTech/DLA')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RFQ.settings')
django.setup()

# Variables from Django settings
DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASSWORD = ''
DB_NAME = 'rfq'
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

# Global variables for hang detection
last_active = time.time()
TIMEOUT_THRESHOLD = 1800  # 30 minutes

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


@retry(max_attempts=5, delay=3)
def extract_unit_from_pdf_comprehensive(pdf_url, driver, max_pdf_retries=3):
    """Enhanced PDF extraction with comprehensive retry logic"""
    unit = "N/A"
    inspection_point = ""
    acceptance_point = ""
    deliver_fob = ""
    deliver_days = ""
    buyer_info = ""
    solicitation_line_number = ""

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

                    with requests.get(
                        pdf_url,
                        cookies=cookies,
                        headers=headers,
                        verify=False,
                        stream=True,
                        timeout=45,
                        allow_redirects=True
                    ) as response:

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

                        except Exception as page_error:
                            print(
                                f"  Error extracting text from page {page_num}: {page_error}")
                            continue

                    if not full_text.strip():
                        raise Exception("No text extracted from any page")

                    print(
                        f"  Total text extracted: {len(full_text)} characters")

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
    print(f"Inspection: {inspection_point[:50]}...")
    print(f"Acceptance: {acceptance_point[:50]}...")
    print(f"Buyer: {buyer_info[:50]}...")

    return unit, inspection_point, acceptance_point, deliver_fob, deliver_days, buyer_info, solicitation_line_number


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
            row_data = {
                "nsn": row.find_element(By.XPATH, ".//td[2]/span/a").text.strip(),
                "nsn_link": row.find_element(By.XPATH, ".//td[2]/span/a").get_attribute("href"),
                "nomenclature": row.find_element(By.XPATH, ".//td[3]/span").text.strip(),
                "solicitation": row.find_element(By.XPATH, ".//td[5]/span/a").text.strip(),
                "status": row.find_element(By.XPATH, ".//td[6]/span").text.strip(),
                "quantity": row.find_element(By.XPATH, ".//td[7]/span").text.strip(),
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
def process_nsn_links_comprehensive(driver, start_time, nsns_to_process=None):
    """Process each unique NSN and create separate records for each CAGE+Part combination.

    If nsns_to_process is provided (list or set of NSN strings), only those NSNs are processed.
    """
    total_rows = len(row_data_list)
    successful_saves = 0
    failed_saves = 0

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
                print(f"Failed to load NSN page for {nsn}")
                failed_saves += 1
                nsn_status[nsn] = "failed"
                nsn_failed_reasons[nsn] = "Failed to load NSN page"
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
                    print(f"No CAGE codes found for NSN {nsn}")
                    failed_saves += 1
                    continue

            except Exception as cage_error:
                print(f"Error finding CAGE table for NSN {nsn}: {cage_error}")
                failed_saves += 1
                nsn_status[nsn] = "failed"
                nsn_failed_reasons[nsn] = f"CAGE table error: {cage_error}"
                continue

            # Get CAGE details ONCE
            print(f"Getting CAGE details for {len(cage_values)} codes...")
            cage_details_list = extract_cage_details_comprehensive(
                driver, cage_values)

            # Extract PDF data ONCE
            try:
                solicitation_table = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//table[@summary='Contains RFQ records for the NSN. ']"))
                )

                pdf_link = WebDriverWait(solicitation_table, 60).until(
                    EC.presence_of_element_located(
                        (By.XPATH, ".//tbody/tr[1]/td[1]/a"))
                )
                pdf_url = pdf_link.get_attribute("href")

                print(f"Extracting PDF data...")
                unit_value, inspection_point, acceptance_point, deliver_fob, deliver_days, buyer_info, solicitation_line_number = extract_unit_from_pdf_comprehensive(
                    pdf_url, driver=driver)
                print(f"PDF extracted - Unit: {unit_value}, Line Number: {solicitation_line_number}")

            except Exception as pdf_error:
                print(f"PDF extraction failed for NSN {nsn}: {pdf_error}")
                unit_value = inspection_point = acceptance_point = deliver_fob = deliver_days = buyer_info = solicitation_line_number = ""

            unit_code = unit_value.strip().upper() if unit_value else 'N/A'
            unit_description = UNIT_MAPPING.get(
                unit_code, f'{unit_code} (Unknown)')
            unit = f"{unit_code} ({unit_description})" if unit_code != 'N/A' else 'N/A'

            if unit == 'N/A' or unit_code == 'N/A':
                print(f"SKIPPING NSN {nsn}: Unit is N/A")
                failed_saves += 1
                nsn_status[nsn] = "failed"
                nsn_failed_reasons[nsn] = "Unit is N/A after PDF extraction"
                continue

            # NEW LOGIC: Create records for each solicitation-CAGE-part combination
            print(f"Creating records for each solicitation-CAGE-part combination...")

            # Process each solicitation separately
            for solicitation_data in nsn_rows:
                solicitation = solicitation_data.get('solicitation', 'N/A')
                raw_quantity = solicitation_data.get('quantity', '0')
                solicitation_quantity = extract_quantity(raw_quantity)

                print(
                    f"\nProcessing solicitation {solicitation} with quantity {solicitation_quantity}")

                # Create record for each CAGE+Part combination with this solicitation's quantity
                for j, cage in enumerate(cage_values):
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
                        'Line Number': solicitation_line_number,  # From PDF extraction
                        'CAGE Code': cage,
                        'Part Number': part_number,
                        'Unit': unit,
                        'Inspection Point': inspection_point,
                        'Acceptance Point': acceptance_point,
                        'Deliver FOB': deliver_fob,
                        'Deliver Days': deliver_days,
                        'Buyer Info': buyer_info
                    }

                    print(
                        f"  Record: SOL={solicitation}, CAGE={cage}, PART={part_number}, QTY={solicitation_quantity}")

                    # Save individual record
                    if save_single_record_to_db(nsn_record, cage_details_list):
                        records_saved_for_nsn += 1
                        successful_saves += 1
                        print(f"    SUCCESS - Individual record saved")
                    else:
                        failed_saves += 1
                        print(f"    FAILED - Database save failed")

            print(
                f"NSN {nsn} COMPLETE: {records_saved_for_nsn} individual records saved")
            print(
                f"Overall progress: {successful_saves} saved, {failed_saves} failed")

            # Mark NSN status based on whether we saved any records
            if records_saved_for_nsn > 0:
                nsn_status[nsn] = "success"
            else:
                nsn_status[nsn] = "failed"
                nsn_failed_reasons[nsn] = "No records were saved for this NSN"

        except Exception as e:
            print(f"ERROR processing NSN {nsn}: {e}")
            failed_saves += 1
            nsn_status[nsn] = "failed"
            nsn_failed_reasons[nsn] = str(e)

    print(f"\nFINAL RESULTS:")
    print(f"   Unique NSNs processed: {len(nsn_groups)}")
    print(f"   Original solicitation rows: {total_rows}")
    print(f"   Individual records saved: {successful_saves}")
    print(f"   Failed saves: {failed_saves}")

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
    return successful_saves, nsn_status


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

            # Navigate to NATO CAGE website
            driver.set_page_load_timeout(30)

            if not safe_get(driver, "https://eportal.nspa.nato.int/Codification/CageTool/CageTool/"):
                print(f"Failed to load NATO website for CAGE {cage_code}")
                cage_cache[cage_code] = cage_data
                extracted_data.append(cage_data)
                continue

            # Wait for page to fully load
            WebDriverWait(driver, 30).until(
                lambda d: d.execute_script(
                    'return document.readyState') == 'complete'
            )
            time.sleep(3)  # Wait for Angular to load

            try:
                # Find and fill CAGE code input
                findCageCodeInput = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.ID, "inputCageCode"))
                )
                findCageCodeInput.clear()
                findCageCodeInput.send_keys(cage_code)

                # Find and click search button
                search_button = WebDriverWait(driver, 60).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, "button.btn.btn-primary[title='Search']"))
                )

                # Use JavaScript click for better reliability
                driver.execute_script("arguments[0].click();", search_button)
                time.sleep(5)  # Wait for search results

                # Check if CAGE code was found
                try:
                    # Look for "No data available" or similar messages
                    no_data_messages = driver.find_elements(
                        By.XPATH, "//*[contains(text(), 'No data') or contains(text(), 'not found') or contains(text(), 'No records')]")
                    if no_data_messages:
                        print(f"CAGE {cage_code} not found in NATO database")
                        cage_cache[cage_code] = cage_data
                        extracted_data.append(cage_data)
                        continue
                except:
                    pass

                # Try to find and click expand button - multiple approaches
                expand_button = None
                expand_attempts = 0
                max_expand_attempts = 3

                while expand_attempts < max_expand_attempts:
                    try:
                        expand_attempts += 1

                        # Comprehensive expand button selectors
                        expand_selectors = [
                            "svg.svg-inline--fa.fa-chevron-right",
                            ".fa-chevron-right",
                            "svg[data-icon='chevron-right']",
                            "button svg.fa-chevron-right",
                            "[class*='chevron-right']",
                            ".btn-outline-primary",
                            ".btn-outline-secondary",
                            ".btn-secondary",
                            "button[class*='btn-outline']",
                            "button[aria-expanded='false']",
                            "button[data-toggle]",
                            "[role='button']"
                        ]

                        for selector in expand_selectors:
                            try:
                                elements = driver.find_elements(
                                    By.CSS_SELECTOR, selector)
                                if elements:
                                    for element in elements:
                                        try:
                                            if element.is_displayed() and element.is_enabled():
                                                expand_button = element
                                                break
                                        except:
                                            continue
                                    if expand_button:
                                        break
                            except:
                                continue

                        # If found, try to click
                        if expand_button:
                            # Scroll into view and click
                            driver.execute_script(
                                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", expand_button)
                            time.sleep(1)

                            try:
                                driver.execute_script(
                                    "arguments[0].click();", expand_button)
                                print(
                                    f"Successfully expanded details for CAGE {cage_code}")
                                break
                            except Exception as e1:
                                try:
                                    expand_button.click()
                                    print(
                                        f"Successfully expanded details for CAGE {cage_code} (normal click)")
                                    break
                                except Exception as e2:
                                    try:
                                        from selenium.webdriver.common.action_chains import ActionChains
                                        actions = ActionChains(driver)
                                        actions.move_to_element(
                                            expand_button).click().perform()
                                        print(
                                            f"Successfully expanded details for CAGE {cage_code} (action chains)")
                                        break
                                    except Exception as e3:
                                        expand_button = None

                        # Wait before retry
                        if expand_attempts < max_expand_attempts:
                            time.sleep(3)

                    except Exception as e:
                        if expand_attempts < max_expand_attempts:
                            time.sleep(2)
                            continue
                        else:
                            break

                # Wait for expanded content
                time.sleep(3)

                # Extract data using comprehensive approach
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
            return True
        else:
            print("  FAILED: Could not update quantity")
            return False

    # ========================
    # INSERT NEW RECORD
    # ========================
    print(
        f"  INSERTING NEW: NSN={nsn}, CAGE={cage_code}, PART={part_number}, RETURN_BY={return_by}, QTY={new_quantity}")

    sql_query = """
    INSERT INTO solicitations_solicitation 
    (cage, nsn, nomenclature, solicitation, status, quantity, issued_date, return_by_date, 
     organization_name, street_name, city, postal_code, phone, fax, email, part_number, unit, 
     inspection_point, acceptance_point, deliver_fob, deliver_days, buyer_info, scraped_date, solicitation_line_number)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            record_data.get('Buyer Info', ''), datetime.date.today(),
            record_data.get('Line Number', '')
        )

        cursor.execute(sql_query, db_record)
        print(f"  SUCCESS: New record inserted with quantity {new_quantity}")
        return True

    except Exception as e:
        print(f"  Error inserting new record: {e}")
        return False
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


def main():
    start_time = time.time()
    max_retries = 2
    retry_count = 0
    driver = None

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
                return

            # Navigate to website with SSL error handling
            if not safe_get(driver, WEBSITE_URL):
                print("Failed to load website after multiple attempts")
                return

            print('=' * 70)
            print("WELCOME TO COMPREHENSIVE RFQ AUTOMATED PROGRAM")
            print('=' * 70)

            # Handle date argument
            formated_date = sys.argv[1] if len(sys.argv) > 1 else None
            print(
                f"Requested date: {formated_date}" if formated_date else "No date specified - will use first available date")

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
                    return
            else:
                print("No date links found in the RFQ dates table")
                return

            # Main scraping workflow
            print("Starting comprehensive data extraction...")

            # Check for pagination and handle accordingly
            if check_if_single_page(driver):
                print("Single page detected, extracting data from single page...")
                extract_data_from_page(driver, wait)
            else:
                print("Multiple pages detected, starting pagination...")
                handle_pagination(driver, wait)

            print(
                f"Total records extracted from all pages: {len(row_data_list)}")

            if not row_data_list:
                print("No data extracted. Exiting.")
                return

            # Process NSN links and save each record immediately (first pass)
            print("Processing NSN links and saving each record immediately (first pass)...")
            total_saved_first, nsn_status_first = process_nsn_links_comprehensive(
                driver, start_time
            )

            print(
                f"First pass completed: {total_saved_first} records saved to database")

            # Determine which NSNs failed in the first pass
            failed_nsns_first = [
                nsn for nsn, status in nsn_status_first.items() if status == "failed"
            ]

            total_saved_second = 0
            nsn_status_second = {}

            # Optional second pass: retry only failed NSNs once more
            if failed_nsns_first:
                print("\nStarting second pass to retry failed NSNs...")
                print("NSNs to retry:")
                for nsn in failed_nsns_first:
                    print(f"  - {nsn}")

                total_saved_second, nsn_status_second = process_nsn_links_comprehensive(
                    driver, start_time, nsns_to_process=set(failed_nsns_first)
                )

                print(
                    f"Second pass completed: {total_saved_second} additional records saved to database"
                )
            else:
                print("\nNo NSNs failed in first pass; skipping second pass.")

            overall_saved = total_saved_first + total_saved_second
            print(f"Completed: {overall_saved} total records saved to database")

            end_time = time.time()
            total_time = end_time - start_time
            print(
                f"Script completed successfully in {total_time/60:.2f} minutes ({total_time:.2f} seconds)")
            print(f"Processed {len(row_data_list)} total records")
            print(
                f"Average time per record: {total_time/len(row_data_list):.2f} seconds" if row_data_list else "No records processed")

            # Performance summary with cache statistics
            print("\n" + "="*60)
            print("PERFORMANCE SUMMARY:")
            print(f"Processed {len(row_data_list)} total records")
            print(f"Successfully saved {overall_saved} records to database")
            print(
                f"Average time per record: {total_time/len(row_data_list):.2f} seconds" if row_data_list else "No records processed")

            print(f"Cache file location: {CACHE_FILE_PATH}")
            print(f"Cache duration: {CACHE_DURATION_DAYS} days")
            print("="*60)

            break

        except Exception as e:
            retry_count += 1
            print(f"Attempt {retry_count} failed: {str(e)}")
            traceback.print_exc()
            if retry_count >= max_retries:
                print("Max retries reached. Exiting.")
                break
            time.sleep(5)
        finally:
            try:
                if driver:
                    driver.quit()
                    print("WebDriver closed successfully")
            except:
                pass


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
