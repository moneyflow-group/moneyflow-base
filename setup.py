from setuptools import setup, find_packages
# To use a consistent encoding
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()


setup(
    name='moneyflow-base',
    version='0.1.4',  # Required
    description='Moneyflow Base library',
    long_description=long_description,
    url='https://github.com/moneyflow-group/moneyflow-base',
    author='Moneyflow Group A/S',  # Optional
    author_email='support@moneyflow.io',  # Optional
    classifiers=[  # Optional
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6',
    ],
    keywords='base lib utilities',
    packages=['mbase', ], # find_packages(exclude=['example', 'docs', 'venv', 'web', 'db']),
    install_requires=['dramatiq'], #['flask', 'flask_restful', 'markupsafe', 'waitress', 'flask_login'],
    project_urls={  # Optional
        'Bug Reports': 'https://github.com/moneyflow-group/moneyflow-base/issues',
        'Source': 'https://github.com/moneyflow-group/moneyflow-base/',
    },
)
