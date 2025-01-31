DLA - Government Tender Extraction and RFQ System
Overview
DLA is a Django-based application designed to automatically extract government tenders and associated OEM (Original Equipment Manufacturer) data. The system stores this information in a MySQL database and allows users to select tenders and send RFQs (Request for Quotations) to OEMs.
The extraction process can run automatically every day or be triggered manually by an admin for a specific date. The project utilizes Selenium for web scraping, MySQL for data storage, and JavaScript with Bootstrap CSS for the frontend.
Features
•	Automated Tender Extraction: Fetches government tenders and associated OEM data automatically every day.
•	Manual Extraction: Admin can select a specific date to extract tender data.
•	Tender Management: Users can browse extracted tenders and select them for further actions.
•	RFQ Sending: Users can send RFQs to OEMs directly from the system.
•	Database Storage: All extracted tenders and OEM data are stored in MySQL.
•	User-friendly Interface: Built with JavaScript and Bootstrap for a smooth user experience.
Technologies Used
•	Backend: Django (Python), Selenium
•	Frontend: JavaScript, Bootstrap CSS
•	Database: MySQL
Installation
Prerequisites
Ensure you have the following installed on your system:
•	Python 3.x
•	Django
•	MySQL
•	Selenium WebDriver (ChromeDriver)
Steps
1.	Clone the repository: 
2.	git clone https://github.com/Staphord/DLA
3.	cd dla
4.	Create and activate a virtual environment: 
5.	python -m venv venv
6.	source venv/bin/activate  # On Windows use `venv\Scripts\activate`
7.	Install dependencies: 
8.	pip install -r requirements.txt
9.	Set up MySQL database: 
o	Create a MySQL database for the project.
o	Update the settings.py file with the database credentials:
10.	DATABASES = {
11.	    'default': {
12.	        'ENGINE': 'django.db.backends.mysql',
13.	        'NAME': 'your_database_name',
14.	        'USER': 'your_mysql_user',
15.	        'PASSWORD': 'your_mysql_password',
16.	        'HOST': 'localhost',
17.	        'PORT': '3306',
18.	    }
19.	}
20.	Run database migrations: 
21.	python manage.py migrate
22.	Create a superuser (for admin access): 
23.	python manage.py createsuperuser
24.	Run the development server: 
25.	python manage.py runserver
26.	Access the application: Open http://127.0.0.1:8000/ in your web browser.
Usage
•	Admin Dashboard: Log in with the admin credentials to manually extract tenders and manage data.
•	Tender Extraction: Automatic extraction runs daily, or the admin can trigger it manually.
•	RFQ Sending: Select a tender and send RFQs to the listed OEMs.
Contact
For any inquiries, contact gilgal2020@gmail.com or visit the project repository at https://github.com/your-repo/dla.

