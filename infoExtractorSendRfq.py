import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
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
DB_PORT = settings.DB_PORT
EMAIL_ADDRESS = settings.DEFAULT_FROM_EMAIL
EMAIL_PASSWORD = settings.EMAIL_HOST_PASSWORD

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
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),options=chrome_options)

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
    print('--------------------------------------------------------------------------')
    print(f"Raw argument received: {raw_arg}")  # Debugging: Check full raw input

    try:
        # Parse the JSON argument
        data = json.loads(raw_arg)
        print('--------------------------------------------------------------------------')
        print(f"Decoded JSON: {data}")

        # Extract user_data, mail_data and solicitations
        user_data = data.get("user_data", {})
        solicitations = data.get("solicitations", [])
        mail_data = data.get("mail_data", [])

        print(f'mail data are: {mail_data}')

        # Extract the username from user_data
        username = user_data.get("username")
        print('--------------------------------------------------------------------------')
        print(f"Extracted username: {username}")

        # Retrieve the CustomUser instance from the database
        try:
            created_by_user = CustomUser.objects.get(username=username)
            print('--------------------------------------------------------------------------')
            print(f"Retrieved CustomUser instance: {created_by_user}")

        except CustomUser.DoesNotExist:
            print(f"Error: No CustomUser found with username '{username}'")
            sys.exit(1)  # Exit the script with an error code

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
def fetch_cage_codes(user_data, solicitations):
    connection = None
    try:
        # Establish connection to MySQL
        connection = MySQLdb.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            port=DB_PORT,
            cursorclass=DictCursor
        )
        cursor = connection.cursor()

        # Extract username from user_data
        username = user_data.get("username")
        if not username:
            print("Error: Username is missing in user_data.")
            return []

        # Fetch user ID from the CustomUser table
        user_query = "SELECT id FROM accounts_customuser WHERE username = %s"
        cursor.execute(user_query, (username,))
        user_row = cursor.fetchone()
        if not user_row:
            print(f"Error: User '{username}' not found.")
            return []
        user_id = user_row["id"]

        # Step 1: Check and update or insert OEMUser entries
        for solicitation in solicitations:
            cage_code = solicitation.get("cage")
            print(f'CAGE CODE FETCHED {cage_code}')
            if not cage_code:
                print("Skipping solicitation: Missing cage code.")
                continue

            # Check if OEM exists in the OEM table
            oem_query = "SELECT id FROM solicitations_oem WHERE cage = %s"
            cursor.execute(oem_query, (cage_code,))
            oem_row = cursor.fetchone()

            if not oem_row:
                # Insert new OEM if not found
                insert_oem_query = "INSERT INTO solicitations_oem (cage) VALUES (%s)"
                try:
                    cursor.execute(insert_oem_query, (cage_code,))
                    connection.commit()
                    print(f"OEM with cage code '{cage_code}' added.")
                except MySQLdb.MySQLError as e:
                    print(f"Failed to insert OEM '{cage_code}': {e}")
                    continue

                # Fetch the newly inserted OEM ID
                cursor.execute(oem_query, (cage_code,))
                oem_row = cursor.fetchone()

            oem_id = oem_row["id"]

            # Check if the user is linked to the OEM
            oem_user_query = """
            SELECT is_disabled FROM solicitations_oemuser
            WHERE user_id = %s AND oem_id = %s
            """
            cursor.execute(oem_user_query, (user_id, oem_id))
            oem_user_row = cursor.fetchone()

            if not oem_user_row:
                # Add a new link if not present
                insert_oem_user_query = """
                INSERT INTO solicitations_oemuser (user_id, oem_id, is_disabled)
                VALUES (%s, %s, FALSE)
                """
                try:
                    cursor.execute(insert_oem_user_query, (user_id, oem_id))
                    connection.commit()
                    print(f"Linked user ID '{user_id}' to OEM ID '{oem_id}'.")
                except MySQLdb.MySQLError as e:
                    print(f"Error linking user ID '{user_id}' to OEM ID '{oem_id}': {e}")

        # Step 2: Retrieve enabled OEMs for the logged-in user
        enabled_oems_query = """
        SELECT o.cage
        FROM solicitations_oemuser ou
        JOIN solicitations_oem o ON ou.oem_id = o.id
        WHERE ou.user_id = %s AND ou.is_disabled = FALSE
        """
        cursor.execute(enabled_oems_query, (user_id,))
        enabled_cages = [row["cage"] for row in cursor.fetchall()]

        if not enabled_cages:
            print("No enabled OEMs found for the user.")
            return []

        # Step 3: Fetch solicitations for the enabled CAGE codes and selected IDs
        selected_ids = [solicitation.get("id") for solicitation in solicitations if "id" in solicitation]
        if not selected_ids:
            print("No selected IDs provided.")
            return []

        format_strings_cages = ', '.join(['%s'] * len(enabled_cages))
        format_strings_ids = ', '.join(['%s'] * len(selected_ids))
        solicitation_query = f"""
        SELECT id, cage, nomenclature, quantity, return_by_date, NSN
        FROM solicitations_solicitation
        WHERE cage IN ({format_strings_cages}) AND id IN ({format_strings_ids})
        """
        cursor.execute(solicitation_query, enabled_cages + selected_ids)

        # Fetch all rows
        cage_data = cursor.fetchall()
        count_cage = len(cage_data)
        print('--------------------------------------------------------------------------')
        print(f"Total solicitations to receive RFQ Email: {count_cage}")
        print(f'MY CAGE DATA ARE {cage_data}')
        return cage_data
    

    except MySQLdb.MySQLError as err:
        print(f"Database Error: {err}")
        return []

    finally:
        if connection:
            cursor.close()
            connection.close()

if len(sys.argv) > 1:
    raw_arg = sys.argv[1]
    print(f"Raw argument received: {raw_arg}")  # Debugging: Check full raw input

    try:
        # Parse the JSON argument
        data = json.loads(raw_arg)
        print(f"Decoded JSON: {data}")

        # Extract user_data and solicitations
        user_data = data.get("user_data", {})
        solicitations = data.get("solicitations", [])

        # Retrieve the solicitations
        cage_data = fetch_cage_codes(user_data, solicitations)
        print("Fetched Cage Data:", cage_data)

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON argument: {e}")
else:
    print("No arguments provided to the script.")

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
        # Use `filter` to fetch all matching records and take the first one
        oem_record = OEM.objects.filter(cage=cage_code).first()

        if oem_record:
            # Update the existing record
            oem_record.name = organization_name
            oem_record.street = street_name
            oem_record.city = city_name
            oem_record.postal_code = postal_code
            oem_record.phone = phone
            oem_record.fax = fax
            oem_record.email = email
            oem_record.save()
            print(f"OEM record updated for CAGE Code {cage_code}.")
        else:
            # Create a new record if none exists
            OEM.objects.create(
                cage=cage_code,
                name=organization_name,
                street=street_name,
                city=city_name,
                postal_code=postal_code,
                phone=phone,
                fax=fax,
                email=email,
            )
            print(f"OEM record created for CAGE Code {cage_code}.")
    except Exception as e:
        print(f"Error saving data for CAGE Code {cage_code}: {e}")


# Function to send an email
def send_email(to_email,nomenclature,quantity,return_by_date,nsn,user_data,rfq_unique_id,sent_at):
    from_email = EMAIL_ADDRESS
    password = EMAIL_PASSWORD

    try:
        with open("email.html", "r") as file:
            email_content = file.read()

        ## Prepare dynamic data to be rendered on email
        email_content = email_content.replace("{nomenclature}", nomenclature)
        email_content = email_content.replace("{quantity}", str(quantity))
        email_content = email_content.replace("{return_by_date}", str(return_by_date))
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
        base_url = "http://localhost:8000" 
        #logo_url = f"{base_url}{user_data['logo']}"
        logo_url = 'https://cdn.pixabay.com/photo/2020/08/05/13/27/eco-5465459_1280.png'
        email_content = email_content.replace("{logo}", f'<img src="{logo_url}" alt="Company Logo" style="width: 150px;">')

        # Generate a unique link to the form using the actual rfq.unique_id
        form_link = f"http://localhost:8000/solicitations/myform?rfq_unique_id={rfq_unique_id}"
        email_content = email_content.replace("{form_link}", form_link)

        email_content = email_content.replace("{heading}", mail_data['heading'])
        email_content = email_content.replace("{body}", mail_data['body'])
        email_content = email_content.replace("{salutation}", mail_data['salutation'])

    except FileNotFoundError:
        print("Error: 'email.html' file not found.")
        return

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = "REQUEST FOR QUOTATION"

    msg.attach(MIMEText(email_content, 'html'))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
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

# Process each record
for record in cage_data:
    cage_code = record['cage']
    nomenclature = record['nomenclature']
    quantity = record['quantity']
    return_by_date = record['return_by_date']
    nsn = record['NSN']
    record_id = record['id']  # Use the record's unique ID for email tracking

    try:
        print('--------------------------------------------------------------------------')
        print(f"Processing CAGE Code: {cage_code} | Record ID: {record_id}")

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

        # Extract the organization name (assuming it's always the second element)
        organization_name = read_only_elements[1].text.strip()  # Index 1 corresponds to the organization name
        print(f"Extracted Organization Name: {organization_name}")

        # Locate the street
        street_name = read_only_elements[10].text.strip()  # Index 10 corresponds to the street name
        print(f"Extracted Street Name: {street_name}")

        # City
        city = read_only_elements[12].text.strip()  # Index 12 corresponds to the city
        print(f"Extracted City Name: {city}")

        # Postal code
        postal_code = read_only_elements[13].text.strip()  # Index 13 corresponds to the postal code
        print(f"Extracted Postal Code: {postal_code}")

        # Locate phone and fax information
        phone_fax = driver.find_elements(By.CSS_SELECTOR, "div.ng-star-inserted > div.ng-star-inserted > span")
        phone = phone_fax[0].text.strip()  # Index 0 corresponds to the phone
        print(f"Extracted Phone: {phone}")

        # Locate the fax container using the label
        fax_container = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.XPATH, "//label[contains(text(), 'Fax(es)')]/following-sibling::div"))
        )
        fax_content = fax_container.text.strip()
        print(f"Extracted Fax: {fax_content}")

        # Locate the email element
        email_element = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='mailto:']"))
        )
        email_href = email_element.get_attribute("href")
        email = email_href.replace("mailto:", "").strip()
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

        # Retrieve or create the Solicitation object using the unique record ID
        solicitation, created = Solicitation.objects.get_or_create(
            id=record_id,  # Use the unique ID to differentiate records
            defaults={'nomenclature': nomenclature, 'quantity': quantity}
        )

        if created:
            print(f"Solicitation created for item: {nomenclature}")
        else:
            print(f"Solicitation retrieved for item: {nomenclature}")

        # Call the create_rfq function after sending the email
        rfq = create_rfq(solicitation, oem, created_by=created_by_user)

        print("Preparing to send email...")

        try:
            send_email(
                "williamdemo01@gmail.com",
                nomenclature,
                quantity,
                return_by_date,
                nsn,
                user_data,
                rfq.unique_id,
                rfq.sent_at
            )
        except Exception as e:
            print(f"Failed to send email: {e}")

        # Refresh the page for the next record
        driver.get(website)

    except Exception as e:
        print(f"Error processing CAGE Code {cage_code}: {e}")
        time.sleep(5)

driver.quit()