# DLA New

DLA New is a Django-based RFQ and solicitation management system for procurement workflows. It helps users manage solicitation records, OEM/client information, send RFQ emails, review replies, assess bids, export data, and run background processing tasks.

The application is built around:
- Django 4.2
- MySQL
- Redis
- Django-Q2 for asynchronous job processing
- Azure OpenAI / OpenAI integration
- Bootstrap-based web UI

---

## Project Overview

This project is designed for:
- collecting and tracking solicitations
- managing client and OEM data
- generating and sending RFQ emails
- reviewing RFQ replies
- exporting reports and assessment data
- running scheduled or background scraping / processing tasks

The main application area is the `solicitations` app, and the user/authentication model lives in `accounts`.

---

## Tech Stack

- Python 3.10+ (recommended)
- Django 4.2.17
- MySQL 8.x / MariaDB compatible
- Redis 6+
- django-q2
- django-redis
- mysqlclient
- Selenium / BeautifulSoup / requests / pdf tooling for scraping and parsing
- Azure OpenAI / OpenAI API integration

---

## Repository Structure

```text
DLA-NEW/
├── .env                             # Environment variables for secrets and runtime settings
├── .gitignore
├── manage.py                        # Django entry point
├── requirements.txt                 # Python dependencies
├── README.md                        # Project documentation
├── RFQ/                             # Django project package
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py                  # Project configuration
│   ├── urls.py                     # Root URL patterns
│   ├── wsgi.py
│   ├── wsgi_static_patch.py
│   └── middleware/
├── accounts/                        # Authentication and user/client account logic
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   ├── templates/
│   └── migrations/
├── solicitations/                   # Main business logic app
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── consumers.py
│   ├── context_processors.py
│   ├── email_backend.py
│   ├── export_utils.py
│   ├── forms.py
│   ├── models.py
│   ├── rfq_id_utils.py
│   ├── routing.py
│   ├── signals.py
│   ├── tasks.py
│   ├── tasksorg.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   ├── middleware/
│   ├── management/
│   ├── migrations/
│   ├── static/
│   └── templates/
├── media/                           # User uploads, logos, exports, and generated files
├── static/                          # Global static files if used by the project
├── staticfiles/                     # Collected static after collectstatic
├── venv/                            # Local virtual environment (if used)
├── azure_openai_client.py
├── extractRfqReplies.py
├── extractSolicitations.py
├── extractSolicitationsOld.py
├── gpt4_email_extractor.py
├── gpt4_pdf_extractor.py
├── infoExtractorSendRfq.py
├── email.html
└── ...
```

---

## Prerequisites

Before running the project, install the following:

- Python 3.10 or newer
- MySQL server
- Redis server
- Git
- A browser for the web app
- Optional: a local web server such as Nginx for production deployment

For Windows, you may need the MySQL client build tools depending on your Python version. In many cases, `mysqlclient` will install successfully using a wheel, but on some systems you may need MySQL C headers and build tools.

---

## Environment Configuration

This project uses a `.env` file for runtime and secret settings. The root `.env` file should contain values such as:

```env
USE_AZURE_OPENAI=True
AZURE_OPENAI_API_KEY=your_azure_key
AZURE_OPENAI_ENDPOINT=https://your-resource.services.ai.azure.com/openai/v1
AZURE_OPENAI_DEPLOYMENT=gpt-5-mini
AZURE_OPENAI_API_VERSION=2024-12-01-preview

DEBUG=True
SECRET_KEY=replace-with-a-secure-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1,192.168.252.43,*
CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
FORCE_SCRIPT_NAME=/DLA

DB_HOST=127.0.0.1
DB_NAME=rfqnew
DB_USER=rfqnew
DB_PASSWORD=your_db_password
DB_PORT=3306

EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_email@gmail.com
DEFAULT_FROM_EMAIL=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_app_password

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=1
Q_CLUSTER_NAME=dla-new-solicitations
Q_CLUSTER_REDIS_DB=2
Q_CLUSTER_WORKERS=4
```

Important notes:
- Do not commit real secrets to source control.
- Use your own MySQL username/password and app email credentials.
- If you run behind a subpath like `/DLA`, keep `FORCE_SCRIPT_NAME=/DLA` consistent with the server config.
- Make sure there are no trailing quotes in your `.env` values.

---

## Setup Steps

### 1. Clone the project

```bash
git clone <your-repository-url>
cd DLA-NEW
```

### 2. Create a virtual environment

Windows:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

If `mysqlclient` fails to install, install the required system packages for MySQL development headers first, then retry.

### 4. Prepare MySQL

Create a database and user for the project if needed:

```sql
CREATE DATABASE rfqnew CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Then create or update a user with access to that database. Example:

```sql
CREATE USER 'rfqnew'@'127.0.0.1' IDENTIFIED BY 'your_db_password';
GRANT ALL PRIVILEGES ON rfqnew.* TO 'rfqnew'@'127.0.0.1';
FLUSH PRIVILEGES;
```

### 5. Start Redis

Redis is required for Django-Q and caching. On Windows you can use a local Redis service or a Redis-compatible installation. On Linux/macOS:

```bash
redis-server
```

### 6. Run migrations

```bash
python manage.py migrate
```

If this is a clean install, Django will create the database tables defined in the app models.

### 7. Collect static files

```bash
python manage.py collectstatic --noinput
```

This is especially important when using a subpath like `/DLA` or when running in production-like settings.

---

## Running the Project

### Local development server

```bash
python manage.py runserver 0.0.0.0:8000
```

Then open:

```text
http://localhost:8000/
```

If the application is served under a subpath, use:

```text
http://localhost:8000/DLA/
```

### Django-Q worker

This app uses Django-Q for asynchronous jobs. Start the worker process:

```bash
python manage.py qcluster
```

For systems that require a long-lived background worker, run it in a persistent terminal or service environment.

---

## Important Runtime Notes

### Subpath deployment

The project includes `FORCE_SCRIPT_NAME = /DLA` and URL helpers that assume the application may run under `/DLA`. If your web server is routing behind a prefix, keep the static and media paths consistent with that prefix.

### Static files

The project’s templates expect static assets to exist under the app static folder. If assets are missing or the folder was renamed, CSS and JavaScript will not load correctly.

### Media files

User uploads, logos, and generated exports are stored under the `media/` folder.

### Background tasks

Some features depend on Redis and Django-Q. If the queue is not running, background processing and scheduled jobs may fail or stall.

---

## Common Commands

Check project health:

```bash
python manage.py check
```

Create migrations after model changes:

```bash
python manage.py makemigrations
```

Apply migrations:

```bash
python manage.py migrate
```

Create a superuser:

```bash
python manage.py createsuperuser
```

Run tests:

```bash
python manage.py test
```

Collect static files:

```bash
python manage.py collectstatic --noinput
```

---

## Typical Application Flow

A typical usage flow for the system is:

1. Admin or user logs in
2. Solicitation data is scraped or imported
3. OEM/client records are created or managed
4. RFQs are prepared and sent
5. Replies are collected and parsed
6. Items are assessed and exported
7. Background tasks handle processing and progress monitoring

---

## Development Tips

- Keep the `.env` file local and never commit it.
- If the app stops loading CSS or media, check static path mapping and `FORCE_SCRIPT_NAME`.
- If background tasks are failing, verify Redis is running and `python manage.py qcluster` is active.
- If MySQL is rejecting connections, confirm the user/host and password match the values in `.env`.
- Run `python manage.py check` after any config changes.

---

## Support / Troubleshooting

Common problems:
- MySQL access denied
- Redis connection errors
- static asset 404 errors
- subpath URL mismatch
- missing environment variables

Most of these come from incorrect `.env` values or missing infrastructure services.

---

## Summary

DLA New is a procurement RFQ workflow platform built with Django. It combines user management, solicitation processing, OEM management, RFQ email workflows, reporting, and asynchronous task processing. Proper setup requires MySQL, Redis, environment variables, and Django-Q workers.

This project is best run in a local development environment using a Python virtual environment, configured MySQL database, and active Redis instance.
