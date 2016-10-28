from distutils.core import setup
from setuptools import find_packages

setup(
    name='sunet-pages-api',
    version='0.0.1',
    license='BSD',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    entry_points={
          'console_scripts': ['sunet-pages-api=sunet_pages_api:main']
    }
)
