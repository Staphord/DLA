 DLA — Government Tender Extraction and RFQ System

 Overview
 DLA is a Django-based system that extracts government solicitations, enriches them with OEM (Original Equipment Manufacturer) data, and streamlines RFQ (Request for Quotation) workflows. It stores data in MySQL, lets users manage solicitations, send RFQs, and track OEM replies to prepare tender submissions.

 Key Features
 - Automated extraction: Daily/background extraction of solicitations and OEM data
 - Manual extraction: Admin-triggered extraction for a specific date
 - RFQ workflow: Create and send RFQs to OEMs; track replies and documents
 - User accounts: Custom user model with profile fields and admin management
 - Background jobs: Uses Django Q for scheduled/async tasks
 - Email integration: SMTP-based sending and processing of RFQ emails
 - UI: Bootstrap-based frontend with project-specific static assets

 Tech Stack
 - Backend: Django (Python), Selenium (for scraping)
 - Database: MySQL
 - Task queue: Django Q
 - Frontend: HTML, JavaScript, Bootstrap

 Repository Layout (high level)
 - `RFQ/`: Project settings and entry points
 - `solicitations/`: Core app for solicitations, RFQs, tasks, templates, static files
 - `accounts/`: Custom user model and auth-related views/templates
 - `media/`: Uploaded files (logos and RFQ reply documents)
 - `static/`: App static assets (served via `collectstatic` in production)
 - `venv/`: Local virtual environment (optional, not in production)

 Project Structure
 ```
 DLA/
 ├─ manage.py                   # Django management entry-point
 ├─ requirements.txt            # Python dependencies
 ├─ README.md                   # Project documentation
 ├─ email.html                  # Email template used in RFQ flows
 ├─ extractSolicitations.py     # Script to extract solicitations (scraping)
 ├─ infoExtractorSendRfq.py     # Script to process & send RFQs
 ├─ cage_cache_90day.pkl        # Cached dataset (domain-specific cache)
 ├─ media/                      # User-uploaded and processed files
 │  ├─ logos/                   # Company logos
 │  └─ replies/                 # OEM reply documents and attachments
 ├─ RFQ/                        # Django project configuration
 │  ├─ __init__.py
 │  ├─ asgi.py                  # ASGI config
 │  ├─ wsgi.py                  # WSGI config
 │  ├─ urls.py                  # Root URL routing
 │  └─ settings.py              # Django settings 
 ├─ solicitations/              # Core app: solicitations, RFQs, email, tasks
 │  ├─ __init__.py
 │  ├─ admin.py                 # Admin registrations
 │  ├─ apps.py                  # AppConfig
 │  ├─ consumers.py             # WebSocket consumers 
 │  ├─ context_processors.py    # Template context helpers
 │  ├─ email_backend.py         # Email utilities/integration
 │  ├─ forms.py                 # Django forms for views/templates
 │  ├─ middleware/              # Custom middleware (timezone etc.)
 │  ├─ migrations/              # Database schema migrations
 │  ├─ models.py                # ORM models (Solicitation, RFQ, etc.)
 │  ├─ routing.py               # Channels routing 
 │  ├─ signals.py               # Model signal handlers
 │  ├─ static/                  # App static files (css/js/img/vendor)
 │  ├─ tasks.py                 # Background jobs (Django Q tasks)
 │  ├─ templates/               # HTML templates for the app
 │  ├─ tests.py                 # Unit/feature tests
 │  ├─ urls.py                  # App URL routing
 │  └─ views.py                 # HTTP views/controllers
 ├─ accounts/                   # Accounts app with custom user model
 │  ├─ __init__.py
 │  ├─ admin.py                 # Admin registrations for user model
 │  ├─ apps.py                  # AppConfig
 │  ├─ forms.py                 # Signup/login/profile forms
 │  ├─ migrations/              # User model migrations
 │  ├─ models.py                # `accounts.CustomUser` and related models
 │  ├─ templates/               # Account-related templates (auth, profile)
 │  ├─ tests.py                 # Tests for accounts
 │  ├─ urls.py                  # Routes for accounts
 │  └─ views.py                 # Views for authentication/profile
 └─ venv/                       # Local virtual environment (dev only)
 ```

 File and Directory Explanations
 - `manage.py`: Runs Django commands (migrate, runserver, qcluster, etc.).
 - `RFQ/settings.py`: All core settings; 
 - `RFQ/urls.py`: Root URL dispatcher; includes app URLs.
 - `RFQ/wsgi.py` and `RFQ/asgi.py`: Deployment entry points for WSGI/ASGI servers.
 - `solicitations/models.py`: Database schema for solicitations, RFQs, chats, email settings, and related data.
 - `solicitations/tasks.py`: Long-running/background jobs for email processing, scheduling (Django Q).
 - `solicitations/templates/`: Templates for listing solicitations, RFQ pages, email content, etc.
 - `solicitations/static/`: Frontend assets; includes vendor libraries.
 - `solicitations/management/commands/`: Custom CLI commands (e.g., to trigger extraction) runnable via `python manage.py <command>`.
 - `accounts/models.py`: Custom user (`AUTH_USER_MODEL`) and related profile fields.
 - `media/`: User-uploaded content and OEM RFQ reply files. 
 - `extractSolicitations.py`, `infoExtractorSendRfq.py`: Top-level scripts for scraping and RFQ sending used in automation/manual runs.
 - `requirements.txt`: Locked set of Python dependencies to reproduce environments.

 Prerequisites
 - Python 3.10+
 - MySQL 8.x (or compatible)
 - Chrome + ChromeDriver (for Selenium-based scraping)

 Quick Start (Windows PowerShell)
 1. Clone the repository
    - `git clone https://github.com/Staphord/DLA.git`
    - `cd DLA`
 2. Create and activate a virtual environment
    - `python -m venv venv`
    - `venv\Scripts\Activate.ps1`
 3. Install dependencies
    - `pip install -r requirements.txt`
 4. Configure environment variables (recommended)
    - in settings.py set django q, databases credentials, email cerdentials as seen in code file:
      ```
    - `CREATE DATABASE rfq CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`
    - `CREATE USER 'rfq'@'%' IDENTIFIED BY 'your_password';`
    - `GRANT ALL PRIVILEGES ON rfq.* TO 'rfq'@'%';`
 6. Run migrations and create a superuser
    - `python manage.py migrate`
    - `python manage.py createsuperuser`
 7. Start services
    - Web server: `python manage.py runserver`
    - Task worker (Django Q): `python manage.py qcluster`
 8. Open the app
    - Visit `http://127.0.0.1:8000/`

 Configuration
 - Database: Defined in `RFQ/settings.py` (`DATABASES['default']`). Prefer loading from env vars as shown above.
 - Email: SMTP settings in `RFQ/settings.py`. Use an app password for Gmail.
 - Time zone and formats: See `TIME_ZONE`, `USE_TZ`, and `TIME_FORMAT` in `RFQ/settings.py`.
 - Static and media
   - `STATIC_URL=/static/`
   - `MEDIA_URL=/media/`
   - `MEDIA_ROOT=media/`
   - In production, run `python manage.py collectstatic` and serve via a web server (e.g., Nginx).

 Background Jobs (Django Q)
 - Worker: `python manage.py qcluster`
 - Configuration: `Q_CLUSTER` in `RFQ/settings.py`
 - Use scheduled tasks or code-triggered tasks to run extraction, email processing, and housekeeping.

 Data Extraction and RFQs
 - Automatic extraction: Implemented via background jobs; can be scheduled daily.
 - Manual extraction: Available in admin or via management commands.
 - Helper scripts (repository root):
   - `extractSolicitations.py`: Runs solicitation scraping/extraction
   - `infoExtractorSendRfq.py`: Processes extraction results and sends RFQs
 - RFQ replies and documents are stored under `media/replies/`.

 Management Commands
 - The `solicitations/management/commands/` directory contains custom commands for extraction, email processing, and maintenance. Run them via:
   - `python manage.py <command_name> [options]`

 Admin and Users
 - Admin site: `/admin/` (use the superuser created earlier)
 - Custom user model: `accounts.CustomUser` (see `accounts/models.py`)

 Development Tips
 - Run tests: `python manage.py test`
 - Create test users and sample data via fixtures or the admin site
 - Use a separate `.env` for local dev vs production

 Deployment Notes
 - Set `DEBUG=False`, configure `ALLOWED_HOSTS`, and secure `SECRET_KEY`
 - Use environment variables for all secrets (DB, SMTP)
 - Run `collectstatic`; serve static/media via a CDN or web server
 - Run multiple Django Q workers and a process supervisor (e.g., systemd)
 - Put the site behind a reverse proxy (Nginx/Apache) with TLS

 Troubleshooting
 - MySQL client/driver issues: Ensure `mysqlclient` is installed (see `requirements.txt`) and MySQL headers are available
 - ChromeDriver mismatch: Match ChromeDriver version to installed Chrome
 - Emails not sending: Verify SMTP credentials and `EMAIL_USE_TLS/PORT`
 - Background jobs not running: Ensure `python manage.py qcluster` is active and check logs

 Security
 - Do not commit secrets (DB credentials, SMTP passwords, secret keys)
 - Move all sensitive settings to environment variables
 - Restrict admin access and enforce strong passwords

 License
 - Add your license here (e.g., MIT, Apache-2.0, or proprietary)

 Contact
 - Email: `gilgal2020@gmail.com`
 - Project URL: add your repository link here

