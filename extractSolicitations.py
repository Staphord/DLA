from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import MySQLdb
from MySQLdb.cursors import DictCursor
import json
import requests
import os
import sys
import django

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

# Configure Chrome options
chrome_options = Options()
chrome_options.add_experimental_option("detach", True)
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--headless")  # Run in headless mode
chrome_options.add_argument("--disable-software-rasterizer")
chrome_options.add_argument("--enable-logging")
chrome_options.add_argument("--v=1")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument('--pageLoadStrategy=normal')

# Initialize WebDriver
PATH = r'C:\Users\chromedriver.exe'
service = Service(executable_path=PATH)
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),options=chrome_options)

# Constants
WEBSITE_URL = "https://www.dibbs.bsm.dla.mil/RFQ"
IMPLICIT_WAIT = 2
driver.implicitly_wait(IMPLICIT_WAIT)

# Navigate to the website
driver.get(WEBSITE_URL)
driver.maximize_window()

# Print welcome message
print('--------------------------------------------------------------------------')
print("WELCOME TO RFQ AUTOMATED PROGRAM")
print('--------------------------------------------------------------------------')

# Handle command-line argument safely
if len(sys.argv) > 1:
    formated_date = sys.argv[1]
    print(f"Scraping for date {formated_date}")
else:
    formated_date = None
    print("No scrape date provided. Skipping date-specific logic.")

# Initialize data storage lists
row_data_list = []
nsn_data_list = []
extracted_data = []
cage_details_list = []

# Utility Functions
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

# Initialize WebDriver wait
wait = WebDriverWait(driver, 10)

# Accept terms and navigate to recent solicitations
click_element(wait, "butAgree")
click_element(wait, "ctl00_cph1_lnkRfqDatesRecent")

# User date input
user_input_date = formated_date if formated_date else None
print(f'USER DATE INPUT IS {user_input_date}')
# Locate the table
table_xpath = "//table[@title='RFQ Download Files' and @summary='Table contains links to RFQ files']"
table = wait.until(EC.presence_of_element_located((By.XPATH, table_xpath)))
# Determine "Post Date" column index
headers = table.find_elements(By.XPATH, ".//thead/tr/th")
post_date_index = next(
    (idx + 1 for idx, header in enumerate(headers) if header.text.strip() == "Post Date"),
    None
)
# Click on the row with the user-specified date
if post_date_index:
    date_links = table.find_elements(By.XPATH, f".//tbody/tr/td[{post_date_index}]//a")
    
    if date_links:
        print("All available dates:")
        for i, link in enumerate(date_links):
            print(f"Date {i}: {link.text.strip()}")
        
        date_to_send = None
        
        if user_input_date:
            # If user provided a date, use it regardless of whether it's found
            date_to_send = user_input_date
            # Still try to find and click the date in the table
            for link in date_links:
                if link.text.strip() == user_input_date:
                    link.click()
                    print(f"Processing data for the specified date: {user_input_date}")
                    break
            else:
                print(f"Date {user_input_date} not found. Using the first available date for clicking: {date_links[0].text.strip()}")
                date_links[0].click()
        else:
            # If no user input date, use the first available date
            date_to_send = date_links[0].text.strip()
            print(f"No user input date. Using first available date: {date_to_send}")
            date_links[0].click()
        
        # Send the appropriate date to Django
        try:
            response = requests.post(
                'http://localhost:8000/solicitations',
                json={'selected_date': date_to_send, 'is_user_input': bool(user_input_date)},
                headers={'Content-Type': 'application/json'}
            )
            if response.status_code == 200:
                print(f"Successfully sent date to Django: {date_to_send}")
            else:
                print(f"Failed to send date to Django. Status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending date to Django: {e}")
    else:
        print("No date links found in the table. Exiting.")
else:
    print("Could not find 'Post Date' column in the table. Exiting.")

# Data extraction functions
def extract_data_from_page():
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
            #print(f"Error processing row: {e}")
            pass


def handle_pagination():
    """Handle pagination and extract data from all pages."""
    page_number = 1  # Start from the first page
    while True:
        try:
            # Wait for the pagination row (the table containing page links)
            pagination_xpath = "//tr[@class='pagination']/td/table/tbody/tr"
            pagination_row = wait.until(EC.presence_of_element_located((By.XPATH, pagination_xpath)))
            
            # Find all page links, excluding 'Next' and 'Previous'
            page_links = pagination_row.find_elements(By.XPATH, ".//td/a[text() and not(contains(text(), 'Next')) and not(contains(text(), 'Previous'))]")
            
            # If the page_number is greater than the number of available pages, break the loop
            if page_number > len(page_links):
                print(f"Page {page_number} exceeds available pages. Stopping.")
                break
            
            # Log the current page number being processed
            print(f"Processing page {page_number}...")
            
            # Get the specific link for the current page number
            page_link = page_links[page_number - 1]  # Subtract 1 because list is 0-indexed
            
            # Extract the JavaScript function from the href attribute
            href_value = page_link.get_attribute("href")
            
            # Extract the part of the href value that triggers the postback (usually something like '__doPostBack('...)
            if href_value and "__doPostBack" in href_value:
                # Execute JavaScript to trigger the postback
                script = href_value.split('javascript:')[1]  # Get the postback script
                driver.execute_script(f"javascript:{script}")

                # Wait for the page to load after the postback
                wait.until(EC.presence_of_element_located((By.XPATH, "//tr[@class='pagination']")))  # Example XPath to wait for page load

                # Extract data from the current page
                extract_data_from_page()

                # Increment the page number for the next iteration
                page_number += 1
            else:
                print(f"Invalid pagination link found at page {page_number}. Skipping...")
                break

        except Exception as e:
            print(f"Error on page {page_number}: {e}")
            break  # Exit the loop on error, or you can continue to handle the error

def process_nsn_links():
    """Visit NSN links and extract CAGE data and part numbers."""
    cage_codes = []  # List to hold extracted CAGE codes

    for row_data in row_data_list:
        try:
            nsn_link = row_data['nsn_link']
            # Open the NSN link in a new tab
            driver.execute_script("window.open(arguments[0]);", nsn_link)
            driver.switch_to.window(driver.window_handles[-1])  # Switch to the new tab

            # Extract CAGE information and part numbers from the NSN details page
            try:
                # Wait for the table containing the CAGE information to be present
                cage_table = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, "//table[@summary='Table conatins Approved Source Data']")))

                # Find all rows in the table body
                cage_rows = cage_table.find_elements(By.XPATH, ".//tbody/tr")
                cage_values = []
                part_numbers = []

                # Loop through each row to extract the CAGE values and part numbers
                for cage_row in cage_rows:
                    try:
                        # Find the CAGE value in the corresponding cell
                        cage_value = cage_row.find_element(By.XPATH, "./td[@headers='h1']").text.strip()
                        # Find the part number in the corresponding cell
                        part_number = cage_row.find_element(By.XPATH, "./td[@headers='h2']").text.strip()
                        
                        cage_values.append(cage_value)
                        part_numbers.append(part_number)
                        cage_codes.append(cage_value)  # Append the CAGE code to the list
                    except Exception as inner_e:
                        print(f"Error extracting CAGE value or part number from a row: {inner_e}")
                        continue

                # Store the list of CAGE values and part numbers as strings, joined by commas
                row_data['cages'] = ", ".join(cage_values)
                row_data['part_numbers'] = ", ".join(part_numbers)

            except Exception as e:
                row_data['cages'] = '-'
                row_data['part_numbers'] = '-'

            finally:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])  # Switch back to the original tab

        except Exception as e:
            print(f"Error processing NSN link for {row_data['nsn']}: {e}")
            continue

    return cage_codes  # Return the list of CAGE codes


def extract_cage_details(cage_codes):
    extracted_data = []  # Initialize the list to hold extracted data

    # Iterate through each CAGE code
    for cage_code in cage_codes:
        try:
            # Navigate to the CageTool page
            driver.get("https://eportal.nspa.nato.int/Codification/CageTool/CageTool/")

            # Locate the input for the CAGE code
            findCageCodeInput = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.ID, "inputCageCode"))
            )

            # Clear the input field and enter the CAGE code
            findCageCodeInput.clear()
            findCageCodeInput.send_keys(cage_code)

            # Locate the search button and click it
            search_button = WebDriverWait(driver, 60).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn.btn-primary[title='Search']"))
            )
            driver.execute_script("arguments[0].click();", search_button)

            # Wait for the expand button and click it
            expand_button = WebDriverWait(driver, 60).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "svg.svg-inline--fa.fa-chevron-right"))
            )
            expand_button.click()

            # Locate all elements with the selector for read-only fields
            read_only_elements = driver.find_elements(By.CSS_SELECTOR, "div.ng-star-inserted > span.readOnly")

            # Extract the information from the read-only fields
            organization_name = read_only_elements[1].text.strip() if len(read_only_elements) > 1 else "N/A"
            street_name = read_only_elements[10].text.strip() if len(read_only_elements) > 10 else "N/A"
            city = read_only_elements[12].text.strip() if len(read_only_elements) > 12 else "N/A"
            postal_code = read_only_elements[13].text.strip() if len(read_only_elements) > 13 else "N/A"

            # Extract phone and fax details
            phone_fax = driver.find_elements(By.CSS_SELECTOR, "div.ng-star-inserted > div.ng-star-inserted > span")
            phone = phone_fax[0].text.strip() if len(phone_fax) > 0 else "N/A"

            # Locate the fax container and extract fax information
            fax_container = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.XPATH, "//label[contains(text(), 'Fax(es)')]/following-sibling::div"))
            )
            fax_content = fax_container.text.strip()

            # Locate and extract the email element
            email_element = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='mailto:']"))
            )
            email_href = email_element.get_attribute("href")
            email = email_href.replace("mailto:", "").strip()

            # Store the extracted data in a dictionary
            cage_data = {
                "CAGE Code": cage_code,
                "Organization Name": organization_name,
                "Street Name": street_name,
                "City": city,
                "Postal Code": postal_code,
                "Phone": phone,
                "Fax": fax_content,
                "Email": email
            }

            # Append the data to the list
            extracted_data.append(cage_data)

            # Debug print to verify extracted data
            print(f"Extracted data for CAGE code {cage_code}: {cage_data}")

        except Exception as e:
            print(f"Error extracting data for CAGE code {cage_code}: {e}")
            continue

    return extracted_data  # Return the extracted data
                

# Function to process collected row data into a structured dictionary
def process_row_data(row_data_list):
    # Loop through the collected row data to populate the dictionary
    for row_data in row_data_list:
        try:
            # Extract common details
            nsn = row_data.get('nsn', 'N/A')
            nomenclature = row_data.get('nomenclature', 'N/A')
            solicitation = row_data.get('solicitation', 'N/A')
            status = row_data.get('status', 'N/A')
            issued_date = row_data.get('issued_date', 'N/A')
            return_by_date = row_data.get('return_by_date', 'N/A')

            # Extract and clean quantity
            raw_quantity = row_data.get('quantity', '0')  # Default to '0' if missing
            quantity = extract_quantity(raw_quantity)

            # Split CAGE codes and part numbers into individual entries if there are multiple
            cage_values = row_data.get('cages', '-').split(', ')
            part_numbers = row_data.get('part_numbers', '-').split(', ')

            # Ensure part_numbers list is at least as long as cage_values
            while len(part_numbers) < len(cage_values):
                part_numbers.append('N/A')

            # Generate a separate dictionary for each CAGE code with its corresponding part number
            for i, cage in enumerate(cage_values):
                cage = cage.strip()  # Trim any extra spaces
                part_number = part_numbers[i].strip() if i < len(part_numbers) else 'N/A'
                
                nsn_entry = {
                    'NSN': nsn,
                    'Nomenclature': nomenclature,
                    'Quantity': quantity,
                    'Solicitation': solicitation,
                    'Status': status,
                    'Issued Date': issued_date,
                    'Return By Date': return_by_date,
                    'CAGE Code': cage if cage else 'N/A',  # Handle empty CAGE values
                    'Part Number': part_number if part_number else 'N/A',  # Handle empty part numbers
                }
                nsn_data_list.append(nsn_entry)

        except Exception as e:
            print(f"Error processing row data into dictionary: {e}")
            continue

    # Print each dictionary for debugging (optional; can be removed in production)
    for nsn_entry in nsn_data_list:
        print(nsn_entry)

    return nsn_data_list


# Database Operations
db_connection = MySQLdb.connect(
    host=DB_HOST,
    user=DB_USER,
    passwd=DB_PASSWORD,
    db=DB_NAME,
    port=DB_PORT,
    cursorclass=DictCursor
)
cursor = db_connection.cursor()


def save_to_db(data_list, cage_details_list):
    """Save extracted data to the database."""
    sql_query = """
    INSERT INTO solicitations_solicitation 
    (cage, nsn, nomenclature, status, quantity, issued_date, return_by_date, 
     organization_name, street_name, city, postal_code, phone, fax, email, part_number)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    for data in data_list:
        try:
            # Find the corresponding CAGE details from cage_details_list
            cage_code = data.get('CAGE Code', 'N/A')
            cage_details = next((item for item in cage_details_list if item['CAGE Code'] == cage_code), None)

            # Debug print to verify matching
            print(f"Looking for CAGE Code: {cage_code}")
            print(f"Found CAGE Details: {cage_details}")

            # If CAGE details are found, use them; otherwise, use default values
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

            # Execute the SQL query with all the data
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
                data.get('Part Number', 'N/A')  # Added part number
            ))
            db_connection.commit()
        except MySQLdb.Error as e:
            print(f"Database error: {e}")
            db_connection.rollback()


# Main workflow
extract_data_from_page()
handle_pagination()
process_nsn_links()
cage_codes = process_nsn_links()  # Extract CAGE codes from NSN links
print(f"CAGE CODES: {cage_codes}")  # Debug print to verify CAGE codes
cage_details_list = extract_cage_details(cage_codes) 
print(f"CAGE DETAILS LIST: {cage_details_list}")
processed_data = process_row_data(row_data_list)
save_to_db(processed_data,cage_details_list)
driver.quit()
