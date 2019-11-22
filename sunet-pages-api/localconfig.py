from pyconfig import Namespace
import os

sunetpages = Namespace()
sunetpages.root = "/var/www"
sunetpages.owner = "www-data"
sunetpages.group = "www-data"
sunetpages.auth_cookie = os.getenv('SUNET_PAGES_AUTH_COOKIE',None)
