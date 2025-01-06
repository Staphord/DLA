import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from urllib.parse import urljoin
import MySQLdb  # Use mysqlclient (MySQLdb)
from MySQLdb.cursors import DictCursor  # Import DictCursor from MySQLdb.cursors
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import time
import os
import django
import sys

# Add project to Python path
sys.path.append('D:/projects/GilTech/RFQ') 
# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RFQ.settings')

# Initialize Django
django.setup()

from django.conf import settings
from solicitations.models import Solicitation,OEM,RFQ,OEMUser
from accounts.models import CustomUser
from django.utils.timezone import now
from django.db import IntegrityError

# Variables from Django settings
DB_HOST = settings.DB_HOST
DB_USER = settings.DB_USER
DB_PASSWORD = settings.DB_PASSWORD
DB_NAME = settings.DB_NAME
EMAIL_ADDRESS = settings.EMAIL_ADDRESS
EMAIL_PASSWORD = settings.EMAIL_PASSWORD

## Setup Chrome options
chrome_options = Options()
chrome_options.add_experimental_option("detach", True)
chrome_options.add_argument("--headless")  # Run in headless mode
chrome_options.add_argument("--disable-gpu")  # Disable GPU usage
chrome_options.add_argument("--disable-software-rasterizer")
chrome_options.add_argument("--enable-logging")
chrome_options.add_argument("--v=1")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument('--pageLoadStrategy=normal')

## Initialize Chrome driver path
PATH = r'C:\Users\chromedriver.exe'
service = Service(executable_path=PATH)
driver = webdriver.Chrome(service=service, options=chrome_options)

## Website URL
website = "https://eportal.nspa.nato.int/Codification/CageTool/CageTool/"

## Wait maximum 2 min before timeout
driver.implicitly_wait(120)

## Render the website
driver.get(website)
driver.maximize_window()

print('--------------------------------------------------------------------------')
print("WELCOME TO RFQ AUTOMATED PROGRAM")
print('--------------------------------------------------------------------------')

# Check if an argument is passed to the script
if len(sys.argv) > 1:
    raw_arg = sys.argv[1]
    print(f"Raw argument received: {raw_arg}")  # Debugging: Check full raw input
    try:
        # Parse the JSON argument
        payload = json.loads(raw_arg)
        print(f"Decoded JSON: {payload}")

        # Extract user data and selected IDs
        user_data = payload.get("user_data", {})
        selected_ids = payload.get("selected_ids", [])

        print(f"user_data: {user_data}")
        print(f"selected_ids: {selected_ids}")

        # Extract the username from user_data
        username = user_data.get("username")  
        print(f"Extracted username: {username}")

        # Retrieve the CustomUser instance from the database
        try:
            created_by_user = CustomUser.objects.get(username=username)
            print(f"Retrieved CustomUser instance: {created_by_user}")
        except CustomUser.DoesNotExist:
            print(f"Error: No CustomUser found with username '{username}'")
            sys.exit(1)  # Exit the script with an error code

        # Process selected IDs
        for solicitation_id in selected_ids:
            print(f"Processing solicitation ID: {solicitation_id}")

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON argument: {e}")
else:
    print("No arguments provided to the script.")

def generate_unique_id(oem):
    """
    Generates a unique ID for an RFQ.

    Format: ABC-MM-CAGE-SEQUENCE
    """
    current_month = now().strftime("%m")  # Get current month as two digits
    oem_prefix = oem.name[:3].upper()  # First three letters of OEM name
    cage_code = oem.cage.upper()  # CAGE code

    # Count existing RFQs for the OEM in the current month
    rfq_count = RFQ.objects.filter(
        oem=oem,
        sent_at__month=now().month
    ).count()

    # Increment sequence number
    sequence_number = rfq_count + 1

    # Generate the unique ID
    unique_id = f"{oem_prefix}-{current_month}-{cage_code}-{sequence_number}"
    return unique_id

## Connect to the MySQL database
def fetch_cage_codes():
    connection = None
    try:
        # Establish connection to MySQL
        connection = MySQLdb.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            cursorclass=DictCursor
        )
        cursor = connection.cursor()

        # Assume user_data contains the logged-in user's data
        username = user_data['username']

        # Step 1: Retrieve enabled OEMs for the logged-in user
        oem_query = """
        SELECT o.cage
        FROM solicitations_oemuser ou
        JOIN solicitations_oem o ON ou.oem_id = o.id
        JOIN accounts_customuser u ON ou.user_id = u.id
        WHERE u.username = %s AND ou.is_disabled = FALSE
        """
        cursor.execute(oem_query, (username,))
        cages = [row['cage'] for row in cursor.fetchall()]

        if not cages:
            # No enabled OEMs, return empty list
            return []

        # Step 2: Fetch solicitations for the enabled CAGE codes
        format_strings = ', '.join(['%s'] * len(cages))
        solicitation_query = f"""
        SELECT cage, item_name, quantity, part_number, NSN
        FROM solicitations_solicitation
        WHERE cage IN ({format_strings})
        """
        cursor.execute(solicitation_query, cages)

        # Fetch all the rows
        cage_data = cursor.fetchall()
        countcage = len(cage_data)
        print(f'Total solicitations to receive RFQ Email {countcage}')
        return cage_data

    except MySQLdb.MySQLError as err:
        print(f"Error: {err}")
        return []

    finally:
        if connection:
            cursor.close()
            connection.close()

# Fetch the solicitations
cage_data = fetch_cage_codes()
print(cage_data)

def create_rfq(solicitation, oem, created_by):
    """
    Creates an RFQ entry in the database.

    Args:
        solicitation (Solicitation): The related solicitation object.
        oem (OEM): The related OEM object.
        created_by (CustomUser): The user who created the RFQ.

    Returns:
        RFQ: The created RFQ object.
    """
    try:
        # Generate a unique ID for the RFQ
        unique_id = generate_unique_id(oem)

        print(f"the generated unique_id is {unique_id}")

        # Create the RFQ with the unique ID
        rfq = RFQ.objects.create(
            solicitation=solicitation,
            oem=oem,
            created_by=created_by,
            unique_id=unique_id  # Assign generated ID
        )
        print(f"RFQ created successfully: {rfq}")
        return rfq
    except IntegrityError as e:
        print(f"Failed to create RFQ due to an integrity error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

## Function to save data to OEM Model
def save_oem_data(cage_code, organization_name, street_name, city_name, postal_code, phone, fax, email):
    try:
        # Use `get_or_create` to find an existing record or create a new one
        oem, created = OEM.objects.get_or_create(
            cage=cage_code,  # Match the record by the `cage` field
            defaults={
                'name': organization_name,
                'street': street_name,
                'city': city_name,
                'postal_code': postal_code,
                'phone': phone,
                'fax': fax,
                'email': email,
            }
        )

        if not created:  # If the record already exists, update the fields
            oem.name = organization_name
            oem.street = street_name
            oem.city = city_name
            oem.postal_code = postal_code
            oem.phone = phone
            oem.fax = fax
            oem.email = email
            oem.save()

        if created:
            print(f"OEM record created for CAGE Code {cage_code}.")
        else:
            print(f"OEM record updated for CAGE Code {cage_code}.")

    except Exception as e:
        print(f"Error saving data for CAGE Code {cage_code}: {e}")

# Function to send an email
def send_email(to_email,item_name,quantity,part_number,nsn,user_data,rfq_unique_id,sent_at):
    from_email = EMAIL_ADDRESS
    password = EMAIL_PASSWORD

    try:
        with open("email.html", "r") as file:
            email_content = file.read()

        ## Prepare dynamic data to be rendered on email
        email_content = email_content.replace("{item_name}", item_name)
        email_content = email_content.replace("{quantity}", str(quantity))
        email_content = email_content.replace("{part_number}", str(part_number))
        email_content = email_content.replace("{NSN}", str(nsn))
        email_content = email_content.replace("{rfq_unique_id}", rfq_unique_id)

        # Format the sent_at date
        formatted_sent_at = sent_at.strftime('%d-%m-%y')
        email_content = email_content.replace("{sent_at}", formatted_sent_at)
        
        # Replace placeholders for user data
        email_content = email_content.replace("{username}", user_data['username'])
        email_content = email_content.replace("{email}", user_data['email'])
        email_content = email_content.replace("{phone}", user_data['phone'])
        email_content = email_content.replace("{address}", user_data['address'])
        email_content = email_content.replace("{companyName}", user_data['companyName'])
        
        # Generate a complete URL for the logo
        base_url = "http://localhost:8000"  # Replace with your server's base URL
        #logo_url = f"{base_url}{user_data['logo']}"
        logo_url = 'https://cdn.pixabay.com/photo/2020/08/05/13/27/eco-5465459_1280.png'
        email_content = email_content.replace("{logo}", f'<img src="{logo_url}" alt="Company Logo" style="width: 150px;">')

        # Generate a unique link to the form using the actual rfq.unique_id
        form_link = f"http://localhost:8000/solicitations/myform?rfq_unique_id={rfq_unique_id}"
        email_content = email_content.replace("{form_link}", form_link)

    except FileNotFoundError:
        print("Error: 'email.html' file not found.")
        return

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = "REQUEST FOR QUOTATION"

    msg.attach(MIMEText(email_content, 'html'))

    try:
        server = smtplib.SMTP("klmestate.com", 587)
        server.starttls()
        server.login(from_email, password)
        server.sendmail(from_email, to_email, msg.as_string())
        print(f"Email successfully sent to {to_email}")
        print('--------------------------------------------------------------------------')
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        driver.get(website)
    finally:
        server.quit()

## Process each record
for record in cage_data:
    cage_code = record['cage']
    item_name = record['item_name']
    quantity = record['quantity']
    part_number = record['part_number']
    nsn = record['NSN']
    try:
        print('--------------------------------------------------------------------------')
        print(f"Processing CAGE Code: {cage_code}")

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

        # Locate all elements with the selector
        read_only_elements = driver.find_elements(By.CSS_SELECTOR, "div.ng-star-inserted > span.readOnly")
        
        ## I USED THIS TODEBUG FOR THE INDEX OF ORGANIZATION NAME BECAUSE OF MULTIPLE RESULTS
        #for index, elem in enumerate(read_only_elements):
           # print(f"Element with read only {index}: {elem.text.strip()}")

        # Extract the organization name (assuming it's always the second element)
        organization_name = read_only_elements[1].text.strip()  # Index 1 corresponds to the organization name
        print(f"Extracted Organization Name: {organization_name}")  

        # Locate the street
        street_name =read_only_elements[10].text.strip()  # Index 10 corresponds to the street name
        print(f"Extracted Street Name: {street_name}") 

        #City
        city = read_only_elements[12].text.strip()  # Index 12 corresponds to the city
        print(f"Extracted City Name: {city}") 
        
        #Postal code
        postal_code = read_only_elements[13].text.strip()  # Index 13 corresponds to the postal code
        print(f"Extracted Postal Code: {postal_code}") 

        # Locate all elements with the selector
        phone_fax = driver.find_elements(By.CSS_SELECTOR, "div.ng-star-inserted > div.ng-star-inserted > span") 

        ## I USED THIS TODEBUG FOR THE INDEX OF PHONE BECAUSE OF MULTIPLE RESULTS
        #for index, elem in enumerate(phone_fax):
            #print(f"Element with span {index}: {elem.text.strip()}")

        #Phone
        phone = phone_fax[0].text.strip()  # Index 0 corresponds to the phone
        print(f"Extracted Phone: {phone}") 

        # Locate the fax container using the label
        fax_container = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.XPATH, "//label[contains(text(), 'Fax(es)')]/following-sibling::div"))
        )

        # Extract the fax text
        fax_content = fax_container.text.strip()
        print(f"Extracted Fax: {fax_content}")

        # Locate the email element
        email_element = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='mailto:']"))
        )
        email_href = email_element.get_attribute("href")
        email = email_href.replace("mailto:", "").strip()

        # Print the extracted details
        print(f"Extracted Email: {email}")

        # Save data to the database
        save_oem_data(
            cage_code=cage_code,
            organization_name=organization_name,
            street_name=street_name,
            city_name=city,
            postal_code=postal_code,
            phone=phone,
            fax=fax_content,
            email=email
        )

        # Retrieve or create the OEM object
        oem = OEM.objects.get(cage=cage_code)

        # Retrieve or create the Solicitation object
        solicitation, created = Solicitation.objects.get_or_create(
            item_name=item_name,
            defaults={'quantity': quantity}  # Add other default fields if required
        )

        if created:
            print(f"Solicitation created for item: {item_name}")
        else:
            print(f"Solicitation retrieved for item: {item_name}")

        # Call the create_rfq function after sending the email
        rfq = create_rfq(solicitation, oem,created_by=created_by_user)
        ##############
        print("Preparing to send email...")
        
        try:
            send_email("williambundala54@gmail.com",item_name,quantity,part_number,nsn,user_data,rfq.unique_id,rfq.sent_at)
        except Exception as e:
            print(f"Failed to send email: {e}")
        ###########

        # Refresh the page for the next record
        driver.get(website)

    except Exception as e:
        print(f"Error processing CAGE Code {cage_code}: {e}")
        time.sleep(5)

driver.quit()