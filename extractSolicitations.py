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
import pdfplumber
import io
import re
import time
from bs4 import BeautifulSoup
import urllib3
import traceback
from urllib3.exceptions import MaxRetryError

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set up Django environment
sys.path.append('D:/projects/GilTech/DLA')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RFQ.settings')
django.setup()
from django.conf import settings

# Variables from Django settings
DB_HOST = settings.DB_HOST
DB_USER = settings.DB_USER
DB_PASSWORD = settings.DB_PASSWORD
DB_NAME = settings.DB_NAME
DB_PORT = settings.DB_PORT

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
chrome_options.add_argument("--single-process")  # For resource-constrained systems
chrome_options.add_argument("--disable-setuid-sandbox")
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--ssl-version-min=tls1')
chrome_options.add_argument('--cipher-suite-blacklist=0x0004,0x0005,0xc011,0xc007')

# Create custom SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Apply to requests
requests.packages.urllib3.disable_warnings()
requests.adapters.DEFAULT_RETRIES = 3

print("STARTING SCRIPT---------------------------------")

# Retry decorator for critical functions
def retry(max_attempts=3, delay=5):
    def decorator(func):
        def wrapper(*args, **kwargs):
            attempts = 0
            last_exception = None
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except (WebDriverException, MaxRetryError, requests.exceptions.RequestException) as e:
                    attempts += 1
                    last_exception = e
                    print(f"Attempt {attempts} failed: {str(e)}")
                    if attempts >= max_attempts:
                        raise last_exception
                    time.sleep(delay)
                    # Reinitialize driver if needed
                    if 'driver' in kwargs:
                        kwargs['driver'].quit()
                        kwargs['driver'] = initialize_driver()
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
            driver.get(url)
            return True
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
    """Robust PDF unit extraction with multiple fallback methods and SSL handling"""
    unit = "N/A"
    print(f"\nExtracting from: {pdf_url}")
    
    # Store the original PDF URL in case we get redirected
    original_pdf_url = pdf_url
    
    try:
        # Store main window handle
        main_window = driver.current_window_handle
        
        try:
            # Open PDF in new tab with safe navigation
            driver.execute_script(f"window.open('{pdf_url}');")
            new_window = [w for w in driver.window_handles if w != main_window][0]
            driver.switch_to.window(new_window)
            
            if not safe_get(driver, pdf_url):
                print(f"Failed to navigate to PDF URL: {pdf_url}")
                return unit
                
            # Handle consent page if it appears
            try:
                consent_button = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.ID, "butAgree"))
                )
                consent_button.click()
                print("Clicked consent button")
                time.sleep(2)
            except:
                pass  # No consent page found

            # Get final URL after any redirects
            final_url = driver.current_url
            print(f"Final URL after navigation: {final_url}")
            
            # Determine which URL to use for PDF download
            use_url = original_pdf_url if original_pdf_url.lower().endswith('.pdf') else final_url
            
            # If we have a PDF URL (either original or final), proceed with download
            if use_url.lower().endswith('.pdf'):
                print(f"Using PDF URL: {use_url}")
                try:
                    cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                    headers = {
                        'User-Agent': 'Mozilla/5.0',
                        'Referer': pdf_url,
                        'Accept': 'application/pdf'
                    }
                    
                    response = requests.get(
                        use_url,
                        cookies=cookies,
                        headers=headers,
                        verify=False,  # Disable SSL verification
                        timeout=30
                    )
                    
                    # Verify PDF content
                    if not response.content.startswith(b'%PDF'):
                        raise ValueError("Not a valid PDF")
                        
                    # Extract text
                    with pdfplumber.open(io.BytesIO(response.content)) as pdf:
                        for i, page in enumerate(pdf.pages[:15]):  # Check first 15 pages
                            text = page.extract_text() or ""
                            
                            # Pattern 1: ITEM NO. SUPPLIES/SERVICES QUANTITY UNIT UNIT PRICE AMOUNT
                            # Example: 0001 6680-01-314-3624 99.000 EA $ ________________ $ ________________
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
                            # Example: 0001 7011317608 0001 PG 1,250.000
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
                                r"QTY:\s*\d+\s+([A-Z]{2})\b",  # QTY: 100 EA
                                r"UNIT\s*[:=]\s*([A-Z]{2})\b",  # UNIT: EA or UNIT=EA
                                r"U/I\s*[:=]\s*([A-Z]{2})\b",   # U/I: EA or U/I=EA
                                r"\b(\d+)\s+([A-Z]{2})\s+@",    # 100 EA @
                                r"Quantity\s*:\s*\d+\s+([A-Z]{2})\b"  # Quantity: 100 EA
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
                                    # Check for UNIT or UI column
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
                                                    
                except requests.exceptions.RequestException as e:
                    print(f"PDF download failed: {str(e)}")
                    return unit
            else:
                print("No valid PDF URL found after navigation")
                return unit
                
        except Exception as e:
            print(f"PDF processing error: {str(e)}")
            traceback.print_exc()
            return unit
            
        finally:
            # Clean up tabs
            try:
                if len(driver.window_handles) > 1:
                    driver.close()
                driver.switch_to.window(main_window)
            except:
                pass
                
    except Exception as e:
        print(f"Critical error in extract_unit_from_pdf: {str(e)}")
        traceback.print_exc()
        
    return unit

@retry(max_attempts=3, delay=5)
def extract_data_from_page(driver, wait):
    """Extract data from the current page."""
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

@retry(max_attempts=3, delay=5)
def handle_pagination(driver, wait):
    """Handle pagination and extract data from all pages."""
    page_number = 1
    while True:
        try:
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
            else:
                print(f"Invalid pagination link at page {page_number}. Skipping...")
                break

        except Exception as e:
            print(f"Error on page {page_number}: {e}")
            break

@retry(max_attempts=3, delay=5)
def process_nsn_links(driver):
    """Visit NSN links and extract CAGE data, part numbers, and UNIT values."""
    cage_codes = []
    
    for row_data in row_data_list:
        try:
            if not check_driver_health(driver):
                raise WebDriverException("Driver connection lost")
                
            nsn_link = row_data['nsn_link']
            driver.execute_script("window.open(arguments[0]);", nsn_link)
            driver.switch_to.window(driver.window_handles[-1])

            try:
                cage_table = WebDriverWait(driver, 10).until(
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

                solicitation_table = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//table[@summary='Contains RFQ records for the NSN. ']"))
                )
                
                pdf_link = WebDriverWait(solicitation_table, 10).until(
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

        except Exception as e:
            print(f"Error processing NSN link: {e}")
    
    return cage_codes

@retry(max_attempts=3, delay=5)
def extract_cage_details(driver, cage_codes):
    extracted_data = []
    
    for cage_code in cage_codes:
        try:
            if not check_driver_health(driver):
                raise WebDriverException("Driver connection lost")
                
            driver.get("https://eportal.nspa.nato.int/Codification/CageTool/CageTool/")
            
            findCageCodeInput = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.ID, "inputCageCode"))
            )
            findCageCodeInput.clear()
            findCageCodeInput.send_keys(cage_code)

            search_button = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn.btn-primary[title='Search']"))
            )
            driver.execute_script("arguments[0].click();", search_button)

            expand_button = WebDriverWait(driver, 30).until(
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

def process_row_data(row_data_list):
    for row_data in row_data_list:
        try:
            nsn = row_data.get('nsn', 'N/A')
            nomenclature = row_data.get('nomenclature', 'N/A')
            solicitation = row_data.get('solicitation', 'N/A')
            status = row_data.get('status', 'N/A')
            issued_date = row_data.get('issued_date', 'N/A')
            return_by_date = row_data.get('return_by_date', 'N/A')
            unit = row_data.get('unit', 'N/A')

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
                nsn_data_list.append(nsn_entry)

        except Exception as e:
            print(f"Error processing row data: {e}")

    return nsn_data_list

def save_to_db(data_list, cage_details_list):
    sql_query = """
    INSERT INTO solicitations_solicitation 
    (cage, nsn, nomenclature, status, quantity, issued_date, return_by_date, 
     organization_name, street_name, city, postal_code, phone, fax, email, part_number, unit)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    fax = cage_details.get('Fax', 'N/A')
                    email = cage_details.get('Email', 'N/A')
                else:
                    organization_name = 'N/A'
                    street_name = 'N/A'
                    city = 'N/A'
                    postal_code = 'N/A'
                    phone = 'N/A'
                    fax = 'N/A'
                    email = 'N/A'

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
                    data.get('Unit', 'N/A')
                ))
                db_connection.commit()
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

            wait = WebDriverWait(driver, 10)

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