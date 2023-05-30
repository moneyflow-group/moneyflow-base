SYSTEM_NAME="moneyflow-base"
INSTALLED_APPS = [
    "django.contrib.sites",
    'django.contrib.contenttypes',
    'mbase.eventlog.Event'
]
DEBUG=True,
IGNORABLE_404_URLS=[r'^favicon\.ico$'],
ROOT_URLCONF="/"
STAGE="dev"
SITE_ID=1
