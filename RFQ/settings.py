import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file (before LOGGING / DEBUG)
load_dotenv(BASE_DIR / '.env')


def _env_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_list(value, default=''):
    if value is None or value == '':
        return default.split(',') if isinstance(default, str) else default
    return [item.strip() for item in str(value).split(',') if item.strip()]


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_bool(os.environ.get('DEBUG'), False)

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-only-placeholder')

# RotatingFileHandler + runserver autoreload = two processes on Windows both
# holding django-debug.log open; rollover then raises PermissionError (WinError 32).
_use_plain_file_handler = sys.platform == 'win32'

if _use_plain_file_handler:
    _file_handler = {
        'level': 'DEBUG',
        'class': 'logging.FileHandler',
        'filename': os.path.join(BASE_DIR, 'django-debug.log'),
        'formatter': 'verbose',
    }
    _rfq_file_handler = {
        'level': 'INFO',
        'class': 'logging.FileHandler',
        'filename': str(BASE_DIR / 'rfq_processing.log'),
        'formatter': 'verbose',
    }
else:
    _file_handler = {
        'level': 'DEBUG',
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': os.path.join(BASE_DIR, 'django-debug.log'),
        'maxBytes': 5 * 1024 * 1024,  # 5 MB
        'backupCount': 7,
        'formatter': 'verbose',
    }
    _rfq_file_handler = {
        'level': 'INFO',
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': str(BASE_DIR / 'rfq_processing.log'),
        'maxBytes': 5 * 1024 * 1024,  # 5 MB
        'backupCount': 10,
        'formatter': 'verbose',
    }

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
    },

    'handlers': {
        'file': _file_handler,
        'rfq_file': _rfq_file_handler,
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },

    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'rfq': {
            'handlers': ['rfq_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },

    'root': {
        'handlers': ['file'],
        'level': 'DEBUG',
    },
}

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

ALLOWED_HOSTS = _env_list(os.environ.get('ALLOWED_HOSTS'), 'localhost,127.0.0.1,192.168.252.43,*')

CSRF_TRUSTED_ORIGINS = _env_list(
    os.environ.get('CSRF_TRUSTED_ORIGINS'),
    'http://localhost:8000,http://127.0.0.1:8000,https://swiftneasyrfq.com,http://swiftneasyrfq.com,https://www.swiftneasyrfq.com,http://www.swiftneasyrfq.com'
)

# HTTPS/SSL Settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = False  # nginx handles the redirect
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# Admin URL configuration for subpath
LOGIN_URL = '/DLA/admin/login/'
LOGIN_REDIRECT_URL = '/DLA/admin/'

# Application definition

INSTALLED_APPS = [
    'django_q',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'solicitations',
    'accounts',
    'django.contrib.humanize',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # 'solicitations.middleware.url_redirect.ForceScriptNameRedirectMiddleware',  # Disabled - nginx handles subpath routing
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Fix admin redirects for subpath
    'RFQ.middleware.admin_subpath.AdminSubpathMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'RFQ.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'solicitations.context_processors.rfq_processing_context',
                'solicitations.context_processors.scraping_progress_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'RFQ.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

# Use environment variable to switch between local and production

DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
DB_NAME = os.environ.get('DB_NAME', 'rfqnew')
DB_USER = os.environ.get('DB_USER', 'rfqnew')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_PORT = os.environ.get('DB_PORT', '3306')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'America/New_York'

USE_I18N = True
USE_TZ = True
TIME_FORMAT = "H:i"  # 24-hour format (e.g., 13:30)
USE_L10N = False  # Disable locale-based formatting

SESSION_ENGINE = 'django.contrib.sessions.backends.db'

SESSION_COOKIE_PATH = None
CSRF_COOKIE_PATH = None

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

MEDIA_ROOT = BASE_DIR / 'media'

FORCE_SCRIPT_NAME = os.environ.get('FORCE_SCRIPT_NAME', '/DLA')

# User uploads (logos, etc.): must include the same subpath as FORCE_SCRIPT_NAME when the app
# is served under /DLA/. Otherwise FileField.url becomes /media/... and the browser hits
# https://host/media/... instead of https://host/DLA/media/... (404 / broken <img>).
_FORCE_SCRIPT_PREFIX = (FORCE_SCRIPT_NAME or '').rstrip('/')
MEDIA_URL = f'{_FORCE_SCRIPT_PREFIX}/media/' if _FORCE_SCRIPT_PREFIX else '/media/'
# Same subpath as MEDIA: {% static %} must resolve under /DLA/ when FORCE_SCRIPT_NAME is set,
# otherwise the browser requests /static/... at the site root (404 behind nginx / wrong host).
STATIC_URL = f'{_FORCE_SCRIPT_PREFIX}/static/' if _FORCE_SCRIPT_PREFIX else '/static/'


# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.CustomUser'


# Email credentials
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = _env_bool(os.environ.get('EMAIL_USE_TLS'), True)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')

REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
REDIS_DB = int(os.environ.get('REDIS_DB', '1'))

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}


# Django Q settings
Q_CLUSTER = {
    # Unique cluster name to avoid conflicts with DLA project
    'name': os.environ.get('Q_CLUSTER_NAME', 'dla-new-solicitations'),
    "redis": {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        # Use db 2 (different from DLA project to isolate task queues)
        "db": int(os.environ.get('Q_CLUSTER_REDIS_DB', '2')),
    },
    'workers': int(os.environ.get('Q_CLUSTER_WORKERS', '4')),
    'recycle': 500,
    # 2 hours timeout for RFQ reply extraction (can process many emails)
    'timeout': 7200,
    'retry': 8000,  # Must be larger than timeout to prevent retriggering before completion
    'compress': True,
    'save_limit': 250,
    'queue_limit': 500,
    'label': 'Django Q (DLA-NEW)',
    'orm': 'default',
    'use_django_timezone': True,
}

BASE_URL = 'https://localhost:8000'  # Update to production URL when deployed

# Azure OpenAI / Azure AI Foundry configuration
USE_AZURE_OPENAI = os.getenv('USE_AZURE_OPENAI', 'True').lower() == 'true'

# Azure OpenAI / Foundry settings
AZURE_OPENAI_API_KEY = os.getenv('AZURE_OPENAI_API_KEY', '')
# Classic: https://your-resource.openai.azure.com/
# Foundry: https://your-resource.services.ai.azure.com/api/projects/your-project
# or https://your-resource.services.ai.azure.com/openai/v1/
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT', '')
AZURE_OPENAI_DEPLOYMENT = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-5-mini')  # Your deployment name
# Used only for classic AzureOpenAI client (ignored for Foundry /openai/v1)
AZURE_OPENAI_API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION', '2024-12-01-preview')

# Standard OpenAI settings (fallback if not using Azure)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = 'gpt-4o'

# Common settings
OPENAI_MAX_RETRIES = 3
OPENAI_TIMEOUT = 30  # seconds

AUTOSEND_SCHEDULE_COOLDOWN_MINUTES = 0
AUTOSEND_DAYS_LOOKBACK = 14