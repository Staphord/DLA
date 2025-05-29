import random
import ssl
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (WebDriverException, 
                                      NoSuchWindowException,
                                      TimeoutException)
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

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set up Django environment
sys.path.append('D:/projects/GilTech/DLA')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RFQ.settings')
django.setup()
from django.conf import settings

# Variables from Django settings
DB_HOST = '168.231.66.43' # settings.DB_HOST
DB_USER = 'rfq' #settings.DB_USER
DB_PASSWORD = 'rfq@0213'  # settings.DB_PASSWORD
DB_NAME = 'rfq' #settings.DB_NAME
DB_PORT = 3306 #settings.DB_PORT

# Configure Chrome options with SSL bypass
chrome_options = Options()
chrome_options.add_experimental_option("detach", True)
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-software-rasterizer")
chrome_options.add_argument("--enable-logging")
chrome_options.add_argument("--v=1")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument('--pageLoadStrategy=normal')
chrome_options.add_argument('--ignore-certificate-errors')
chrome_options.add_argument('--allow-running-insecure-content')
chrome_options.add_argument('--disable-web-security')
chrome_options.add_argument('--disable-extensions')
chrome_options.add_argument('--allow-insecure-localhost')
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--memory-growth=4096")
chrome_options.add_argument("--disable-setuid-sandbox")
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--ssl-version-min=tls1')
chrome_options.add_argument('--cipher-suite-blacklist=0x0004,0x0005,0xc011,0xc007')
chrome_options.add_argument("--disable-http2")
chrome_options.add_argument("--disable-quic")
chrome_options.add_argument("--disable-features=NetworkService")

# Create custom SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Apply to requests
requests.packages.urllib3.disable_warnings()
requests.adapters.DEFAULT_RETRIES = 3

print("STARTING SCRIPT---------------------------------")

# Global variables for hang detection
last_active = time.time()
TIMEOUT_THRESHOLD = 300  # 5 minutes

# Unit code to description mapping
UNIT_MAPPING = {
    'AB': 'BULK PACK',
    'AC': 'ACRE',
    'AD': 'DRAM (MINIM)',
    'AJ': 'COP',
    'AL': 'ACCESS LINES',
    'AM': 'AMPOULE',
    'AO': 'APOTHECARY OUNCE',
    'AP': 'APOTHECARY POUND',
    'AR': 'SUPPOSITORY',
    'AS': 'APOTHECARY SCRUPLE',
    'AT': 'ASSORTMENT',
    'AV': 'CAPSULE',
    'AW': 'POWDER-FILLED VIALS',
    'AX': 'TWENTY',
    'AY': 'ASSEMBLY',
    'B0': 'BRITISH THERMAL UNITS (BTU\'S) PER CUBIC FOOT',
    'B1': 'BARREL, LIQUID',
    'B2': 'BARREL, DRY',
    'B3': 'BATTING POUND',
    'B4': 'BARREL, IMPERIAL',
    'B5': 'BILLET',
    'B6': 'BUN',
    'B7': 'CYCLE',
    'B8': 'BOARD',
    'B9': 'BATT',
    'BA': 'BALL',
    'BB': 'BASS BOX',
    'BC': 'BUCKET',
    'BD': 'BUNDLE',
    'BE': 'BALE',
    'BF': 'BOARD FOOT',
    'BG': 'BAG',
    'BH': 'BRUSH',
    'BI': 'BELT',
    'BJ': 'BAND',
    'BK': 'BOOK',
    'BL': 'BARREL',
    'BM': 'BEAM',
    'BN': 'BULK',
    'BO': 'BOLT',
    'BP': '100 BOARD FEET',
    'BQ': 'BRIQUET',
    'BR': 'BAR',
    'BS': 'BASKET',
    'BT': 'BOTTLE',
    'BU': 'BUSHEL (32 DRY QUARTS)',
    'BV': 'BUSHEL, DRY IMPERIAL',
    'BW': 'BASE WEIGHT',
    'BX': 'BOX',
    'BY': 'BUNKS',
    'BZ': 'BLOCK',
    'C0': 'CALLS',
    'C1': 'COMPOSITE PRODUCT POUNDS (TOTAL WEIGHT)',
    'C2': 'SQUARE CENTIMETER',
    'C3': 'COMBO',
    'C4': 'CARLOAD',
    'C5': 'COST',
    'C6': 'CELL',
    'C7': 'CARSET',
    'C8': 'CUBIC DECIMETER',
    'C9': 'COIL GROUP',
    'CA': 'CARTRIDGE',
    'CB': 'CARBOY',
    'CC': 'CUBIC CENTIMETER',
    'CD': 'CUBIC YARD',
    'CE': 'CONE',
    'CF': 'CUBIC FOOT',
    'CG': 'CENTIGRAM',
    'CH': 'CHAINS (LAND SURVEY)',
    'CI': 'CUBIC INCH',
    'CK': 'CAKE',
    'CL': 'COIL',
    'CM': 'CENTIMETER',
    'CN': 'CAN',
    'CO': 'CONTAINER',
    'CP': 'CRATE',
    'CQ': 'CARD',
    'CR': 'CONNECTOR',
    'CS': 'CASE',
    'CT': 'CARTON',
    'CU': 'CURIE',
    'CV': 'COVER',
    'CW': 'HUNDRED WEIGHT (LONG)',
    'CX': 'CASSETTE',
    'CY': 'CYLINDER',
    'CZ': 'CUBIC METER',
    'DA': 'DAYS',
    'DB': 'DECIBELS',
    'DC': 'DECAGRAM',
    'DE': 'DECIMETER',
    'DF': 'FAHRENHEIT',
    'DG': 'DECIGRAM',
    'DI': 'DISPENSER',
    'DK': 'KELVIN',
    'DL': 'DECILITER',
    'DM': 'DRAM',
    'DO': 'DOLLARS, U.S.',
    'DP': 'DOZEN PAIR',
    'DQ': 'DATA RECORD',
    'DR': 'DRUM',
    'DS': 'DISPLAY',
    'DT': 'DRY TON',
    'DU': 'DYNE',
    'DW': 'PENNYWEIGHT',
    'DX': 'CALENDAR DAYS (NUMBER OF)',
    'DY': 'DIRECTORY BOOKS',
    'DZ': 'DOZEN',
    'E1': 'HECTOMETER',
    'EA': 'EACH',
    'EB': 'ELECTRONIC MAIL BOXES',
    'EE': 'EMPLOYEES',
    'EH': 'KNOTS',
    'EJ': 'LOCATIONS',
    'EP': 'ELEVEN PACK',
    'EQ': 'EQUIVALENT GALLONS',
    'EV': 'ENVELOPE',
    'EX': 'EXPOSURE',
    'F4': 'MINIM',
    'F6': 'PRICE PER SHARE',
    'FA': 'FATHOM',
    'FB': 'FIELDS',
    'FD': 'FOLD',
    'FE': 'TRACK FOOT',
    'FF': 'HUNDRED CUBIC METERS',
    'FG': 'TRANSDERMAL PATCH',
    'FJ': 'SIZING FACTOR',
    'FK': 'FIBERS',
    'FL': 'FLAKE TON',
    'FM': 'MILLION CUBIC FEET',
    'FO': 'FLUID OUNCE',
    'FR': 'FRAME',
    'FT': 'FOOT',
    'FU': 'FURLONG',
    'FV': 'FIVE',
    'FY': 'FIFTY',
    'GB': 'U.S. GALLONS PER MINUTE',
    'GG': 'GREAT GROSS',
    'GI': 'GILL',
    'GL': 'GALLON',
    'GM': 'GRAM',
    'GN': 'GRAIN',
    'GP': 'GROUP',
    'GR': 'GROSS',
    'GT': 'THOUSAND GALLONS PER DAY',
    'GX': 'APOTHECARY GRAIN',
    'H2': 'HALF LITER',
    'H4': 'HECTOLITER',
    'HA': 'HUNDRED CUBIC FEET',
    'HB': 'HOSPITAL BEDS',
    'HC': 'HUNDRED COUNT',
    'HD': 'HUNDRED',
    'HF': 'HUNDRED FEET',
    'HG': 'HECTOGRAM',
    'HH': 'HOGSHEAD',
    'HI': 'HUNDRED SHEETS',
    'HK': 'HANK',
    'HL': 'HUNDRED FEET - LINEAR',
    'HO': 'HUNDRED TROY OUNCES',
    'HP': 'HUNDRED POUNDS',
    'HQ': 'HECTARE',
    'HR': 'HOUR',
    'HS': 'HUNDRED SQUARE FEET',
    'HT': 'HALF HOUR',
    'HW': 'HUNDRED WEIGHT - SHORT (HUNDRED WEIGHT)',
    'HX': 'HUNDRED BOXES',
    'HY': 'HUNDRED YARDS',
    'HZ': 'HALF DOZEN',
    'I1': 'PERSONS, CAPACITY',
    'IG': 'IMPERIAL GALLON',
    'IH': 'INHALER',
    'IM': 'IMPRESSIONS',
    'IN': 'INCH',
    'IP': 'INSURANCE POLICY',
    'IS': 'STOPS',
    'IU': 'INTERNATIONAL UNIT',
    'JB': 'JOB',
    'JG': 'JUG',
    'JO': 'JOINT',
    'JR': 'JAR',
    'JU': 'JUMBO',
    'K2': 'SQUARE KILOMETER',
    'K6': 'KILOLITER',
    'K7': 'KILOWATT',
    'KC': 'KILOCURIE',
    'KE': 'KEG',
    'KF': 'KILOPACKETS',
    'KG': 'KILOGRAM',
    'KH': 'HUNDRED KILOGRAMS',
    'KK': '100 KILOGRAMS',
    'KM': 'KILOMETER',
    'KR': 'KARAT (CARAT)',
    'KT': 'KIT',
    'KU': 'TASK',
    'KV': 'KILOVOLTS',
    'KZ': 'KILOWATT-HOUR',
    'L5': 'LITERS AT 15 DEGREES CELSIUS',
    'LB': 'POUND (AVOIRDUPOIS)',
    'LE': 'LITE',
    'LF': 'LINEAR FOOT',
    'LG': 'LENGTH',
    'LI': 'LITER',
    'LJ': 'LARGE SPRAY',
    'LK': 'LINK',
    'LM': 'LINEAR METER',
    'LN': 'LINEAR INCH',
    'LO': 'LONG TON',
    'LR': 'LAYER(S)',
    'LS': 'LUMP SUM',
    'LT': 'LOT',
    'LY': 'LINEAR YARD',
    'M0': 'MAGNETIC TAPES',
    'M2': 'SQUARE MILE',
    'M3': 'MAT',
    'M5': 'MICROGRAM',
    'M6': 'METRIC TON',
    'MA': 'METRIC NET TON',
    'MB': 'BRITISH THERMAL UNITS (BTUS) PER HOUR',
    'MC': 'THOUSAND CUBIC FEET',
    'MD': 'AIR DRY METRIC TON',
    'ME': 'MEAL',
    'MF': 'THOUSAND FEET',
    'MG': 'MILLIGRAM',
    'MH': 'METRIC',
    'MI': 'MILE',
    'MJ': 'METRIC GROSS TON',
    'MK': 'METRIC LONG TON',
    'ML': 'MILLILITER',
    'MM': 'MILLIMETER',
    'MO': 'MONTHS',
    'MQ': '1000 METERS',
    'MR': 'METER',
    'MS': 'SQUARE MILLIMETER',
    'MT': 'MINUTES',
    'MX': 'THOUSAND',
    'MZ': 'MIXED',
    'N2': 'NUMBER OF LINES',
    'N7': 'PARTS',
    'N9': 'CARTRIDGE NEEDLE',
    'NA': 'MILLIGRAMS PER KILOGRAM',
    'NB': 'BARGE',
    'NC': 'CAR',
    'ND': 'NET BARRELS',
    'NE': 'NET LITERS',
    'NF': 'MESSAGES',
    'NG': 'NET GALLONS',
    'NI': 'NET IMPERIAL GALLONS',
    'NJ': 'NUMBER OF SCREENS',
    'NK': 'NIGHTS',
    'NL': 'LOAD',
    'NM': 'NAUTICAL MILE',
    'NN': 'TRAIN',
    'NS': 'SHORT TON',
    'NT': 'TRAILER',
    'NV': 'VEHICLE',
    'NX': 'PARTS PER THOUSAND',
    'OA': 'PANEL',
    'OC': 'BILLBOARD',
    'OL': 'OUTLET',
    'OP': 'TWO PACK',
    'OT': 'OUTFIT',
    'OU': 'OPERATING UNIT',
    'OZ': 'OUNCE - AV',
    'P0': 'PAGES - ELECTRONIC',
    'P1': 'PERCENT',
    'P2': 'POUNDS PER FOOT',
    'P3': 'THREE PACK',
    'P4': 'FOUR-PACK',
    'P5': 'FIVE-PACK',
    'P6': 'SIX PACK',
    'P7': 'SEVEN PACK',
    'P8': 'EIGHT-PACK',
    'P9': 'NINE PACK',
    'PA': 'PAGE',
    'PB': 'PAIR INCHES',
    'PC': 'PIECE',
    'PD': 'PAD',
    'PE': 'POUNDS EQUIVALENT',
    'PF': 'PALLET (LIFT)',
    'PG': 'PACKAGE',
    'PH': 'PACK (PAK)',
    'PI': 'PILLOW',
    'PJ': 'PALLET/UNIT LOAD',
    'PK': 'PECK, DRY U.S.',
    'PL': 'PAIL',
    'PM': 'PLATE',
    'PN': 'PERSON',
    'PO': 'POUNDS GROSS',
    'PP': 'PINT, IMPERIAL',
    'PQ': 'PECK DRY IMPERIAL',
    'PR': 'PAIR',
    'PS': 'POUNDS NET',
    'PT': 'PINT',
    'PU': 'MASS POUNDS',
    'PV': 'HALF PINT',
    'PX': 'PELLET',
    'PY': 'PITCH',
    'PZ': 'PACKET',
    'QC': 'CHANNEL',
    'QE': 'PHOTOGRAPHS',
    'QF': 'QUARTER',
    'QI': 'QUART, IMPERIAL',
    'QK': 'QUARTER KILOGRAM',
    'QR': 'QUIRE',
    'QS': 'QUART, DRY U.S.',
    'QT': 'QUART',
    'QU': 'QUARTER DOZEN',
    'R4': 'CALORIE',
    'R5': 'THOUSANDS OF DOLLARS',
    'R9': 'THOUSAND CUBIC METERS',
    'RA': 'RATION',
    'RB': 'RADIAN',
    'RC': 'ROD (AREA) - 16.25 SQUARE YARDS',
    'RD': 'ROUND',
    'RG': 'RING',
    'RH': 'RUNNING OR OPERATING HOURS',
    'RK': 'ROLL-METRIC MEASURE',
    'RL': 'REEL',
    'RM': 'REAM',
    'RN': 'REAM-METRIC MEASURE',
    'RO': 'ROLL',
    'RP': 'POUNDS PER REAM',
    'RR': 'RACK',
    'RS': 'RESETS',
    'RT': 'REVENUE TON MILES',
    'RU': 'RUN',
    'RX': 'THOUSAND ROUNDS',
    'S5': 'SIXTY-FOURTHS OF AN INCH',
    'S6': 'SESSIONS',
    'S7': 'STORAGE UNITS',
    'S8': 'SHELF PACKAGE',
    'S9': 'SLIP SHEET',
    'SA': 'SANDWICH',
    'SB': 'SHIPMENT',
    'SC': 'SECONDS',
    'SD': 'SKID',
    'SE': 'SET',
    'SF': 'SQUARE FOOT',
    'SG': 'SEGMENT',
    'SH': 'SHEET',
    'SI': 'SQUARE INCH',
    'SJ': 'SACK',
    'SK': 'SKEIN',
    'SL': 'SPOOL',
    'SM': 'SQUARE METER',
    'SN': 'SECTION (640 ACRES OR ONE SQUARE MILE)',
    'SO': 'SHOT',
    'SP': 'STRIP',
    'SQ': 'SQUARE',
    'SR': 'SPLIT TANKTRUCK',
    'SS': 'SHEET-METRIC MEASURE',
    'ST': 'SEAT',
    'SU': 'SQUARE ROD',
    'SV': 'SERVICE',
    'SW': 'STANDARD ADVERTISING UNITS (SAUS)',
    'SX': 'STICK',
    'SY': 'SQUARE YARD',
    'SZ': 'SYRINGE',
    'T1': 'THOUSAND POUNDS GROSS',
    'T2': 'TEASPOON',
    'T3': 'THOUSAND PIECES',
    'T4': 'THOUSAND BAGS',
    'T5': 'THOUSAND CASINGS',
    'T6': 'THOUSAND GALLONS',
    'T7': 'THOUSAND IMPRESSIONS',
    'T8': 'THOUSAND LINEAR INCHES',
    'T9': 'THOUSAND KILOWATT HOURS/MEGAWATT-HOUR',
    'TA': 'TENTH CUBIC FOOT',
    'TB': 'TABLESPOON',
    'TC': 'TRUCKLOAD',
    'TD': 'TWENTY-FOUR',
    'TE': 'TEN',
    'TF': 'TWENTY-FIVE',
    'TG': 'GROSS TON',
    'TH': 'THOUSAND KILOGRAMS',
    'TI': 'THOUSAND SQUARE INCHES',
    'TJ': 'THOUSAND SQ. CENTIMETERS',
    'TK': 'TANK',
    'TL': 'THOUSAND LINEAR METERS',
    'TM': 'THOUSAND FEET (BOARD)',
    'TN': 'NET TON (2,000 POUNDS)',
    'TO': 'TROY OUNCE',
    'TP': 'TROY POUND',
    'TQ': 'THOUSAND FEET',
    'TR': 'TEN SQUARE FEET',
    'TS': 'THIRTY-SIX',
    'TT': 'TABLET',
    'TU': 'TUBE',
    'TV': 'TEN-PACK',
    'TW': 'THOUSAND SHEETS',
    'TX': 'THOUSAND LINEAR YARDS',
    'TY': 'TRAY',
    'TZ': 'THOUSAND SQUARE FEET',
    'U1': 'TREATMENTS',
    'U5': 'TWO HUNDRED FIFTY',
    'U6': 'U.S. GALLONS AT 60 DEGREES FAHRENHEIT',
    'UH': 'TEN THOUSAND YARDS',
    'UL': 'UNITLESS',
    'UM': 'MILLION UNITS',
    'UN': 'UNIT',
    'UP': 'TROCHE',
    'UQ': 'WAFER',
    'US': 'UNITED STATES PHARMACOPOEIA (USP)UNIT',
    'V1': 'FLAT',
    'V2': 'POUCH',
    'VC': 'FIVE HUNDRED',
    'VI': 'VIAL',
    'VS': 'VISIT',
    'VT': 'VOLT',
    'W2': 'WET KILO',
    'WB': 'WET POUND',
    'WD': 'WORK DAYS',
    'WE': 'WET TON',
    'WG': 'WINE GALLON',
    'WH': 'WHEEL',
    'WK': 'WEEK',
    'WR': 'WRAP',
    'WT': 'WATT',
    'X2': 'BUNCH',
    'X3': 'CLOVE',
    'X4': 'DROP',
    'X5': 'HEAD',
    'X6': 'HEART',
    'X7': 'LEAF',
    'X8': 'LOAF',
    'X9': 'PORTION',
    'Y1': 'SLICE',
    'Y4': 'TUB',
    'YD': 'YARD',
    'YL': '100 LINEAR YARDS',
    'YR': 'YEARS',
    'YS': 'SLEEVE',
    'YT': 'BYTES',
    'Z1': 'LIFT VAN',
    'Z2': 'CHEST',
    'Z3': 'CASK',
    'Z5': 'LUG',
    'ZF': 'MILLION BTUS/DEKATHERM'
}

def check_for_hang():
    global last_active
    if time.time() - last_active > TIMEOUT_THRESHOLD:
        raise RuntimeError("Script appears to be hung - restarting")
    last_active = time.time()

def cleanup_resources(driver):
    try:
        # Close all but the main window
        while len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
            
        # Clear browser cache periodically
        driver.execute_script("window.open('');")
        driver.switch_to.window(driver.window_handles[-1])
        driver.get('chrome://settings/clearBrowserData')
        time.sleep(1)
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
    except Exception as e:
        print(f"Cleanup error: {e}")

def is_valid_pdf(content):
    # Check for PDF magic number
    if not content.startswith(b'%PDF'):
        return False
        
    # Check for PDF end marker
    if b'%%EOF' not in content[-1024:]:  # Check last 1KB
        return False
        
    return True

# Retry decorator for critical functions
def retry(max_attempts=3, delay=5, cleanup_func=None):
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
                    
                    # Perform cleanup if provided
                    if cleanup_func:
                        try:
                            cleanup_func()
                        except Exception as ce:
                            print(f"Cleanup failed: {ce}")
                            
                    if attempts >= max_attempts:
                        raise last_exception
                    time.sleep(delay * attempts)  # Exponential backoff
            return None
        return wrapper
    return decorator

def initialize_driver():
    """Initialize WebDriver with robust error handling and SSL bypass"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            service = Service(
                executable_path=ChromeDriverManager().install(),
                port=random.randint(10000, 20000)  # Random port to avoid conflicts
            )
            
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(5)
            
            # Verify connection
            driver.get("about:blank")
            return driver
            
        except Exception as e:
            retry_count += 1
            print(f"WebDriver initialization attempt {retry_count} failed: {str(e)}")
            if retry_count >= max_retries:
                raise RuntimeError(f"Failed to initialize WebDriver after {max_retries} attempts")
            time.sleep(5)

def safe_get(driver, url, max_retries=3):
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
            # Try to stop loading
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
    """Extract integer quantity from raw string."""
    try:
        return int(raw_quantity.split("QTY:")[1].strip())
    except (IndexError, ValueError):
        return None

def click_element(wait, locator, by=By.ID):
    """Click on an element using WebDriverWait."""
    element = wait.until(EC.element_to_be_clickable((by, locator)))
    element.click()

@retry(max_attempts=3, delay=5)
def extract_unit_from_pdf(pdf_url, driver):
    """Direct PDF extraction from downloaded content"""
    unit = "N/A"
    print(f"\nExtracting from: {pdf_url}")
    
    try:
        # First check if URL ends with .pdf
        if not pdf_url.lower().endswith('.pdf'):
            print("URL doesn't appear to be a PDF, but continuing anyway")
        
        # Get cookies from Selenium session
        cookies = {c['name']: c['value'] for c in driver.get_cookies()}
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.dibbs.bsm.dla.mil/',
            'Accept': '*/*',  # Accept any content type
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

        # First make a HEAD request to check if redirects are happening
        try:
            head_response = requests.head(
                pdf_url,
                cookies=cookies,
                headers=headers,
                verify=False,
                allow_redirects=True,
                timeout=30
            )
            final_url = head_response.url
            if final_url != pdf_url:
                print(f"URL redirected to: {final_url}")
                pdf_url = final_url
        except requests.exceptions.RequestException as e:
            print(f"HEAD request failed: {str(e)}")
            # Continue with original URL if HEAD fails

        # Try multiple direct download attempts with exponential backoff
        max_direct_attempts = 3
        direct_attempt = 0
        pdf_content = None
        
        while direct_attempt < max_direct_attempts:
            try:
                with requests.get(
                    pdf_url,
                    cookies=cookies,
                    headers=headers,
                    verify=False,
                    stream=True,
                    timeout=30,
                    allow_redirects=True
                ) as response:
                    # Check status code
                    if response.status_code != 200:
                        print(f"HTTP error: {response.status_code} (Attempt {direct_attempt+1}/{max_direct_attempts})")
                        direct_attempt += 1
                        if direct_attempt < max_direct_attempts:
                            # Exponential backoff
                            sleep_time = 2 ** direct_attempt
                            print(f"Retrying direct download in {sleep_time} seconds...")
                            time.sleep(sleep_time)
                            continue
                        else:
                            # If we've exhausted direct download attempts, try Selenium
                            raise requests.exceptions.HTTPError(f"Status code: {response.status_code}")
                    
                    # Check content type
                    content_type = response.headers.get('Content-Type', '')
                    if 'application/pdf' not in content_type.lower() and 'octet-stream' not in content_type.lower():
                        print(f"Warning: Content-Type is {content_type}, not PDF")
                    
                    # Download full content
                    pdf_content = response.content
                    
                    # Verify PDF signature
                    if not pdf_content.startswith(b'%PDF'):
                        print("First bytes don't match PDF signature, checking more of the content...")
                        
                        # Sometimes PDFs might have some bytes before the %PDF signature
                        # Try to find the PDF signature in the first 1024 bytes
                        pdf_sig_pos = pdf_content.find(b'%PDF', 0, 1024)
                        if pdf_sig_pos >= 0:
                            print(f"Found PDF signature at byte position {pdf_sig_pos}")
                            # Trim content to start at the PDF signature
                            pdf_content = pdf_content[pdf_sig_pos:]
                        else:
                            # If still not found, try another attempt
                            direct_attempt += 1
                            if direct_attempt < max_direct_attempts:
                                print(f"Retrying direct download (Attempt {direct_attempt+1}/{max_direct_attempts})...")
                                time.sleep(2 ** direct_attempt)
                                continue
                            else:
                                raise ValueError("Not a valid PDF")
                    
                    # If we get here, we have a valid PDF
                    break
                    
            except (requests.exceptions.RequestException, ValueError) as e:
                direct_attempt += 1
                if direct_attempt < max_direct_attempts:
                    print(f"Direct download attempt {direct_attempt} failed: {str(e)}. Retrying...")
                    time.sleep(2 ** direct_attempt)
                else:
                    print(f"All direct download attempts failed: {str(e)}. Trying Selenium download...")
                    pdf_content = None
                    break

        # If direct downloads all failed, try Selenium as fallback
        if pdf_content is None:
            original_window = driver.current_window_handle
            driver.execute_script("window.open('');")
            driver.switch_to.window(driver.window_handles[-1])
            
            try:
                # First try just navigating to the PDF and getting page source
                driver.get(pdf_url)
                time.sleep(5)  # Wait for download to potentially complete
                
                # Try a different approach - download using Selenium and fetch the binary data
                # Create a temporary file to save the PDF
                temp_file_fd, temp_file_path = tempfile.mkstemp(suffix='.pdf')
                os.close(temp_file_fd)
                
                try:
                    # Execute download script with proper waits
                    driver.execute_script("""
                        var link = document.createElement('a');
                        link.href = arguments[0];
                        link.download = 'download.pdf';
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);
                    """, pdf_url)
                    
                    # Try to get downloaded file
                    # This would need to be modified based on your specific browser configuration
                    # and download folder settings
                    time.sleep(10)  # Wait for download
                    
                    # Alternative: Use requests again with updated cookies after Selenium navigation
                    updated_cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                    
                    # Try one more direct download with the updated cookies
                    with requests.get(
                        pdf_url,
                        cookies=updated_cookies,
                        headers=headers,
                        verify=False,
                        stream=True,
                        timeout=30,
                        allow_redirects=True
                    ) as response:
                        if response.status_code == 200:
                            pdf_content = response.content
                            if pdf_content.startswith(b'%PDF'):
                                print("Successfully downloaded PDF with updated cookies!")
                            else:
                                pdf_sig_pos = pdf_content.find(b'%PDF', 0, 1024)
                                if pdf_sig_pos >= 0:
                                    pdf_content = pdf_content[pdf_sig_pos:]
                                    print("Found PDF signature in content with updated cookies!")
                                else:
                                    print("Still couldn't get a valid PDF")
                
                except Exception as e:
                    print(f"Error during Selenium download: {str(e)}")
                
                finally:
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
                
            except Exception as e:
                print(f"Selenium download failed: {str(e)}")
                return unit
            finally:
                driver.close()
                driver.switch_to.window(original_window)

        # If we still don't have valid PDF content, give up
        if pdf_content is None or not b'%PDF' in pdf_content[:1024]:
            print("Unable to download valid PDF content. Giving up.")
            return unit

        # Process PDF content
        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                # Rest of your PDF processing code remains the same
                for i, page in enumerate(pdf.pages[:15]):  # Check first 15 pages
                    text = page.extract_text() or ""
                    
                    # Pattern 1: ITEM NO. SUPPLIES/SERVICES QUANTITY UNIT UNIT PRICE AMOUNT
                    pattern1 = re.compile(
                        r"^\d+\s+\d{4}-\d{2}-\d{3}-\d{4}\s+\d+\.\d{3}\s+([A-Z]{2})\s+\$",
                        re.MULTILINE
                    )
                    match1 = pattern1.search(text)
                    if match1:
                        unit = match1.group(1).upper()
                        print(f"Found unit via Pattern1 on page {i+1}: {unit}")
                        return unit
                    
                    # Pattern 2: CLIN PR PRLI UI QUANTITY UNIT PRICE TOTAL PRICE
                    pattern2 = re.compile(
                        r"^\d+\s+\d+\s+\d+\s+([A-Z]{2})\s+[\d,]+\.\d{3}",
                        re.MULTILINE
                    )
                    match2 = pattern2.search(text)
                    if match2:
                        unit = match2.group(1).upper()
                        print(f"Found unit via Pattern2 (UI) on page {i+1}: {unit}")
                        return unit
                    
                    # Enhanced fallback patterns
                    fallback_patterns = [
                        r"QTY:\s*\d+\s+([A-Z]{2})\b",
                        r"UNIT\s*[:=]\s*([A-Z]{2})\b",
                        r"U/I\s*[:=]\s*([A-Z]{2})\b",
                        r"\b(\d+)\s+([A-Z]{2})\s+@",
                        r"Quantity\s*:\s*\d+\s+([A-Z]{2})\b"
                    ]
                    
                    for pattern in fallback_patterns:
                        matches = re.finditer(pattern, text, re.IGNORECASE)
                        for match in matches:
                            unit_candidate = match.group(1) if match.lastindex else match.group(0)
                            if unit_candidate.upper() in ['EA', 'BX', 'PK', 'FT', 'YD', 'GAL', 'LB', 'PG']:
                                unit = unit_candidate.upper()
                                print(f"Found unit on page {i+1} via fallback pattern: {unit}")
                                return unit
                    
                    # Table extraction fallback
                    tables = page.extract_tables()
                    for table in tables:
                        if len(table) > 1:
                            headers = [str(cell).upper().strip() for cell in table[0]]
                            if "UNIT" in headers:
                                unit_col = headers.index("UNIT")
                            elif "UI" in headers:
                                unit_col = headers.index("UI")
                            else:
                                continue
                            
                            for row in table[1:]:
                                if len(row) > unit_col:
                                    unit_candidate = str(row[unit_col]).strip().upper()
                                    if unit_candidate in ['EA', 'BX', 'PK', 'FT', 'YD', 'GAL', 'LB', 'PG']:
                                        unit = unit_candidate
                                        print(f"Found unit in table on page {i+1}: {unit}")
                                        return unit

        except Exception as e:
            print(f"PDF processing error: {str(e)}")
            traceback.print_exc()

    except Exception as e:
        print(f"Critical error in extract_unit_from_pdf: {str(e)}")
        traceback.print_exc()
        
    return unit

@retry(max_attempts=3, delay=5, cleanup_func=cleanup_resources)
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

@retry(max_attempts=3, delay=5, cleanup_func=cleanup_resources)
def handle_pagination(driver, wait):
    """Handle pagination and extract data from all pages."""
    page_number = 1
    while True:
        try:
            check_for_hang()
            if not check_driver_health(driver):
                raise WebDriverException("Driver connection lost")
                
            pagination_xpath = "//tr[@class='pagination']/td/table/tbody/tr"
            pagination_row = wait.until(EC.presence_of_element_located((By.XPATH, pagination_xpath)))
            
            page_links = pagination_row.find_elements(By.XPATH, ".//td/a[text() and not(contains(text(), 'Next')) and not(contains(text(), 'Previous'))]")
            
            if page_number > len(page_links):
                print(f"Page {page_number} exceeds available pages. Stopping.")
                break
            
            print(f"Processing page {page_number}...")
            
            page_link = page_links[page_number - 1]
            href_value = page_link.get_attribute("href")
            
            if href_value and "__doPostBack" in href_value:
                script = href_value.split('javascript:')[1]
                driver.execute_script(f"javascript:{script}")
                wait.until(EC.presence_of_element_located((By.XPATH, "//tr[@class='pagination']")))
                extract_data_from_page(driver, wait)
                page_number += 1
                cleanup_resources(driver)  # Periodic cleanup
            else:
                print(f"Invalid pagination link at page {page_number}. Skipping...")
                break

        except Exception as e:
            print(f"Error on page {page_number}: {e}")
            break

@retry(max_attempts=3, delay=5, cleanup_func=cleanup_resources)
def process_nsn_links(driver):
    """Visit NSN links and extract CAGE data, part numbers, and UNIT values."""
    cage_codes = []
    
    for row_data in row_data_list:
        try:
            check_for_hang()
            if not check_driver_health(driver):
                raise WebDriverException("Driver connection lost")
                
            nsn_link = row_data['nsn_link']
            driver.execute_script("window.open(arguments[0]);", nsn_link)
            driver.switch_to.window(driver.window_handles[-1])

            try:
                cage_table = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.XPATH, "//table[@summary='Table conatins Approved Source Data']"))
                )
                
                cage_rows = cage_table.find_elements(By.XPATH, ".//tbody/tr")
                cage_values = []
                part_numbers = []

                for cage_row in cage_rows:
                    try:
                        cage_value = cage_row.find_element(By.XPATH, "./td[@headers='h1']").text.strip()
                        part_number = cage_row.find_element(By.XPATH, "./td[@headers='h2']").text.strip()
                        cage_values.append(cage_value)
                        part_numbers.append(part_number)
                        cage_codes.append(cage_value)
                    except Exception as e:
                        print(f"Error extracting CAGE/part: {e}")

                row_data['cages'] = ", ".join(cage_values)
                row_data['part_numbers'] = ", ".join(part_numbers)

                solicitation_table = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.XPATH, "//table[@summary='Contains RFQ records for the NSN. ']"))
                )
                
                pdf_link = WebDriverWait(solicitation_table, 60).until(
                    EC.presence_of_element_located((By.XPATH, ".//tbody/tr[1]/td[1]/a"))
                )
                pdf_url = pdf_link.get_attribute("href")
                
                unit_value = extract_unit_from_pdf(pdf_url, driver=driver)
                row_data['unit'] = unit_value
                print(f"Extracted UNIT value for NSN {row_data['nsn']}: {unit_value}")
                
            except Exception as e:
                print(f"Error processing NSN details: {e}")
                row_data['cages'] = '-'
                row_data['part_numbers'] = '-'
                row_data['unit'] = 'N/A'
            
            finally:
                if len(driver.window_handles) > 1:
                    driver.close()
                driver.switch_to.window(driver.window_handles[0])
                cleanup_resources(driver)  # Cleanup after each NSN

        except Exception as e:
            print(f"Error processing NSN link: {e}")
    
    return cage_codes

@retry(max_attempts=3, delay=5, cleanup_func=cleanup_resources)
def extract_cage_details(driver, cage_codes):
    extracted_data = []
    
    for cage_code in cage_codes:
        try:
            check_for_hang()
            if not check_driver_health(driver):
                raise WebDriverException("Driver connection lost")
                
            driver.get("https://eportal.nspa.nato.int/Codification/CageTool/CageTool/")
            
            findCageCodeInput = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.ID, "inputCageCode"))
            )
            findCageCodeInput.clear()
            findCageCodeInput.send_keys(cage_code)

            search_button = WebDriverWait(driver, 60).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn.btn-primary[title='Search']"))
            )
            driver.execute_script("arguments[0].click();", search_button)

            expand_button = WebDriverWait(driver, 60).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "svg.svg-inline--fa.fa-chevron-right"))
            )
            expand_button.click()

            read_only_elements = driver.find_elements(By.CSS_SELECTOR, "div.ng-star-inserted > span.readOnly")
            phone_fax = driver.find_elements(By.CSS_SELECTOR, "div.ng-star-inserted > div.ng-star-inserted > span")
            
            cage_data = {
                "CAGE Code": cage_code,
                "Organization Name": read_only_elements[1].text.strip() if len(read_only_elements) > 1 else "N/A",
                "Street Name": read_only_elements[10].text.strip() if len(read_only_elements) > 10 else "N/A",
                "City": read_only_elements[12].text.strip() if len(read_only_elements) > 12 else "N/A",
                "Postal Code": read_only_elements[13].text.strip() if len(read_only_elements) > 13 else "N/A",
                "Phone": phone_fax[0].text.strip() if len(phone_fax) > 0 else "N/A",
                "Fax": WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.XPATH, "//label[contains(text(), 'Fax(es)')]/following-sibling::div"))
                ).text.strip(),
                "Email": WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='mailto:']"))
                ).get_attribute("href").replace("mailto:", "").strip()
            }
            
            extracted_data.append(cage_data)
            print(f"Extracted data for CAGE code {cage_code}: {cage_data}")

        except Exception as e:
            print(f"Error extracting data for CAGE code {cage_code}: {e}")
    
    return extracted_data

def consolidate_duplicates(nsn_data_list):
    """
    Consolidate records with the same CAGE code, nomenclature, NSN, and return_by_date
    by summing their quantities and keeping one consolidated record.
    """
    print("Starting consolidation process...")
    
    # Dictionary to group records by the consolidation key
    consolidated_dict = defaultdict(list)
    
    # Group records by the consolidation criteria
    for record in nsn_data_list:
        # Create a key based on CAGE Code, Nomenclature, NSN, and Return By Date
        consolidation_key = (
            record.get('CAGE Code', '').strip(),
            record.get('Nomenclature', '').strip(),
            record.get('NSN', '').strip(),
            record.get('Return By Date', '').strip()
        )
        consolidated_dict[consolidation_key].append(record)
    
    # Process consolidated groups
    consolidated_list = []
    
    for key, records in consolidated_dict.items():
        if len(records) == 1:
            # No duplicates, keep the original record
            consolidated_list.append(records[0])
        else:
            # Multiple records found, consolidate them
            cage_code, nomenclature, nsn, return_by_date = key
            print(f"Consolidating {len(records)} records for CAGE: {cage_code}, NSN: {nsn}, Nomenclature: {nomenclature}")
            
            # Take the first record as base and sum quantities
            base_record = records[0].copy()
            total_quantity = 0
            
            # Collect all part numbers (remove duplicates)
            all_part_numbers = set()
            
            for record in records:
                # Sum quantities (handle None values)
                quantity = record.get('Quantity', 0)
                if quantity is not None and isinstance(quantity, (int, float)):
                    total_quantity += quantity
                elif quantity is not None:
                    try:
                        total_quantity += int(quantity)
                    except (ValueError, TypeError):
                        print(f"Warning: Could not convert quantity '{quantity}' to number")
                
                # Collect part numbers
                part_number = record.get('Part Number', '').strip()
                if part_number and part_number != 'N/A':
                    all_part_numbers.add(part_number)
            
            # Update the base record with consolidated data
            base_record['Quantity'] = total_quantity
            
            # Combine part numbers (remove duplicates)
            if all_part_numbers:
                base_record['Part Number'] = ', '.join(sorted(all_part_numbers))
            
            consolidated_list.append(base_record)
            
            print(f"Consolidated to 1 record with total quantity: {total_quantity}")
    
    print(f"Consolidation complete: {len(nsn_data_list)} original records -> {len(consolidated_list)} consolidated records")
    return consolidated_list

def process_row_data(row_data_list):
    temp_nsn_data_list = []
    
    for row_data in row_data_list:
        try:
            check_for_hang()
            nsn = row_data.get('nsn', 'N/A')
            nomenclature = row_data.get('nomenclature', 'N/A')
            solicitation = row_data.get('solicitation', 'N/A')
            status = row_data.get('status', 'N/A')
            issued_date = row_data.get('issued_date', 'N/A')
            return_by_date = row_data.get('return_by_date', 'N/A')
            
            # Get unit code and map to full description
            unit_code = row_data.get('unit', 'N/A').strip().upper()
            unit_description = UNIT_MAPPING.get(unit_code, f'{unit_code} (Unknown)')
            unit = f"{unit_code} ({unit_description})" if unit_code != 'N/A' else 'N/A'

            raw_quantity = row_data.get('quantity', '0')
            quantity = extract_quantity(raw_quantity)

            cage_values = row_data.get('cages', '-').split(', ')
            part_numbers = row_data.get('part_numbers', '-').split(', ')

            while len(part_numbers) < len(cage_values):
                part_numbers.append('N/A')

            for i, cage in enumerate(cage_values):
                cage = cage.strip()
                part_number = part_numbers[i].strip() if i < len(part_numbers) else 'N/A'
                
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
                    'Unit': unit
                }
                temp_nsn_data_list.append(nsn_entry)

        except Exception as e:
            print(f"Error processing row data: {e}")

    # Consolidate duplicates before returning
    consolidated_data = consolidate_duplicates(temp_nsn_data_list)
    return consolidated_data

def save_to_db(data_list, cage_details_list):
    sql_query = """
    INSERT INTO solicitations_solicitation 
    (cage, nsn, nomenclature, status, quantity, issued_date, return_by_date, 
     organization_name, street_name, city, postal_code, phone, fax, email, part_number, unit, scraped_date)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

        for data in data_list:
            try:
                cage_code = data.get('CAGE Code', 'N/A')
                cage_details = next((item for item in cage_details_list if item['CAGE Code'] == cage_code), None)

                if cage_details:
                    organization_name = cage_details.get('Organization Name', 'N/A')
                    street_name = cage_details.get('Street Name', 'N/A')
                    city = cage_details.get('City', 'N/A')
                    postal_code = cage_details.get('Postal Code', 'N/A')
                    phone = cage_details.get('Phone', 'N/A')
                    fax = cage_details.get('Fax', '-')
                    email = cage_details.get('Email', 'N/A')
                else:
                    organization_name = '-'
                    street_name = '-'
                    city = '-'
                    postal_code = '-'
                    phone = '-'
                    fax = '-'
                    email = '-'

                cursor.execute(sql_query, (
                    data.get('CAGE Code', 'N/A'),
                    data.get('NSN', 'N/A'),
                    data.get('Nomenclature', 'N/A'),
                    data.get('Status', 'N/A'),
                    data.get('Quantity', 0),
                    data.get('Issued Date', 'N/A'),
                    data.get('Return By Date', 'N/A'),
                    organization_name,
                    street_name,
                    city,
                    postal_code,
                    phone,
                    fax,
                    email,
                    data.get('Part Number', 'N/A'),
                    data.get('Unit', 'EA (EACH)'),
                    datetime.date.today() 
                ))
                db_connection.commit()
                print(f"Saved consolidated record: CAGE {cage_code}, NSN {data.get('NSN', 'N/A')}, Quantity {data.get('Quantity', 0)}")
                
            except MySQLdb.Error as e:
                print(f"Database error: {e}")
                db_connection.rollback()
    
    except Exception as e:
        print(f"Error connecting to database: {e}")
    finally:
        try:
            db_connection.close()
        except:
            pass

def main():
    max_retries = 3
    retry_count = 0
    driver = None
    
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

            driver.maximize_window()

            print('--------------------------------------------------------------------------')
            print("WELCOME TO RFQ AUTOMATED PROGRAM")
            print('--------------------------------------------------------------------------')

            # Handle date argument
            formated_date = sys.argv[1] if len(sys.argv) > 1 else None
            print(f"Scraping for date {formated_date}" if formated_date else "No scrape date provided")

            wait = WebDriverWait(driver, 60)

            # Accept terms and navigate
            click_element(wait, "butAgree")
            click_element(wait, "ctl00_cph1_lnkRfqDatesRecent")

            # Date selection logic
            table_xpath = "//table[@title='RFQ Download Files' and @summary='Table contains links to RFQ files']"
            table = wait.until(EC.presence_of_element_located((By.XPATH, table_xpath)))

            headers = table.find_elements(By.XPATH, ".//thead/tr/th")
            post_date_index = next(
                (idx + 1 for idx, header in enumerate(headers) if header.text.strip() == "Post Date"),
                None
            )

            if post_date_index:
                date_links = table.find_elements(By.XPATH, f".//tbody/tr/td[{post_date_index}]//a")
                
                if date_links:
                    date_to_send = formated_date if formated_date else date_links[0].text.strip()
                    
                    for link in date_links:
                        if formated_date and link.text.strip() == formated_date:
                            link.click()
                            break
                    else:
                        date_links[0].click()
                    
                    try:
                        response = requests.post(
                            'http://localhost:8000/solicitations/',
                            json={'selected_date': date_to_send, 'is_user_input': bool(formated_date)},
                            headers={'Content-Type': 'application/json'},
                            timeout=10
                        )
                        if response.status_code == 200:
                            print(f"Sent date to Django: {date_to_send}")
                    except requests.exceptions.RequestException as e:
                        print(f"Error sending date: {e}")
                else:
                    print("No date links found")
            else:
                print("Post Date column not found")

            # Main workflow
            extract_data_from_page(driver, wait)
            handle_pagination(driver, wait)
            cage_codes = process_nsn_links(driver)
            cage_details_list = extract_cage_details(driver, cage_codes)
            processed_data = process_row_data(row_data_list)
            save_to_db(processed_data, cage_details_list)
            break
            
        except Exception as e:
            retry_count += 1
            print(f"Attempt {retry_count} failed: {str(e)}")
            traceback.print_exc()
            if retry_count >= max_retries:
                print("Max retries reached. Exiting.")
                break
            time.sleep(10)
        finally:
            try:
                if driver:
                    driver.quit()
            except:
                pass
            print("Script execution completed")

if __name__ == "__main__":
    main()