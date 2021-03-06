#!/usr/bin/env python

import pyconfig

import logging
import sys
import csv
import os
import re
import datetime
import workerpool
import git
import signal
import yaml
import subprocess
import StringIO
import copy
import docker

from werkzeug.exceptions import BadRequest, NotFound, Unauthorized
from werkzeug.contrib.fixers import ProxyFix
from multiprocessing import Pool

from flask import Flask, Response, request, jsonify

app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app)

sys.path.append(".")
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s',
                    stream=sys.stderr)

stage_dir = pyconfig.get("sunetpages.staging", "/var/cache/sunetpages")
pub_dir = pyconfig.get("sunetpages.root", "/var/www")
auth_cookie = pyconfig.get("sunetpages.auth_cookie",None)
sites = dict()

signal.signal(signal.SIGUSR1, pyconfig.reload)

@pyconfig.reload_hook
def _reload():
   global sites
   cfg_file = pyconfig.get("sunetpages.config",os.environ.get('SUNET_PAGES_CONFIG',None))
   if cfg_file is not None:
      with open(cfg_file) as fd:
         sites = yaml.load(fd)
      logging.debug(sites)

_reload()

def _urls(r):
   return [r[n] for n in ['clone_url','git_url','ssh_url']]

def _name(r):
   return r['full_name']

def _find_config(r):
   global sites
   return [(name,copy.deepcopy(config)) for name,config in sites.iteritems() if 'git' in config and config['git'] in _urls(r)]

def _sync_links(links, path, root):
   logging.info("synchronizing links for %s <- %s in %s" % (path, ",".join(links), root))
   seen = dict()
   for link in links:
      if os.path.islink(link) and not os.path.readlink(link) == path:
         os.unlink(link)
      if not os.path.exists(link) and path != link:
         os.link(path, link)
      seen[link] = True
   for d in os.listdir(root):
      if os.path.islink(link) and os.path.readlink(link) == path and link not in seen:
         os.unlink(d)

def _checkout_tracking(repo, branch):
   origin = repo.remotes.origin
   remote_ref = getattr(origin.refs, branch)
   if not hasattr(repo.heads,branch):
      repo.create_head(branch, remote_ref)
   local_ref = getattr(repo.heads, branch)
   local_ref.set_tracking_branch(remote_ref)
   local_ref.checkout()

def _site_fetch(local_path, pub_path, config):
   if 'git' in config:
      repo_url = config['git']
      branch = config.get('branch','master')
      if os.path.exists(local_path):
         logging.info("pulling from %s to %s" % (repo_url,local_path))
         repo = git.Repo(local_path)
         repo.head.reset(index=True, working_tree=True)
         _checkout_tracking(repo, branch)
         repo.remotes.origin.pull()
      else:
         logging.info("cloning %s into %s" % (repo_url,local_path))
         repo = git.Repo.clone_from(repo_url, local_path)
         _checkout_tracking(repo, branch)
   else:
     raise ValueError("Unknown repository type")

def _site_update_config(local_path, config):
   pub_conf = os.path.join(local_path,".sunet-pages.yaml")
   if os.path.exists(pub_conf):
      with open(pub_conf) as fd:
         cfg = yaml.load(fd)
         config.update(cfg)
 
def _pstart(args, outf=None, ignore_exit=False):
    env = {}
    logging.debug(" ".join(args))
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return proc


def _p(args, outf=None, errf=None, ignore_exit=False):
    proc = _pstart(args)
    out, err = proc.communicate()
    if err is not None and len(err) > 0:
        logging.error(err)
    if outf is not None:
        with open(outf, "w") as fd:
            fd.write(out)
    else:
        if out is not None and len(out) > 0:
            logging.debug(out)
    if errf is not None:
        with open(errf, "w") as fd:
            fd.write(err)
    else:
        if err is not None and len(err) > 0:
            logging.debug(err)
    rv = proc.wait()
    if rv and not ignore_exit:
        raise RuntimeError("command exited with code != 0: %d" % rv)

def _site_publish(local_path, pub_path, config):
   local_path = local_path.rstrip("/")
   pub_path = pub_path.rstrip("/")
   publish = config.get('publish', ['rsync','--exclude=.git','--delete','-az'])
   publish += ["%s/" % local_path, "%s/" % pub_path]
   docker_image = config.get('docker', None)

   if docker_image is not None:
      if ':' not in docker_image:
         docker_image = "{!s}:latest".format(docker_image)
      dc = docker.from_env()
      img = dc.images.pull(docker_image)
      logging.debug("about to docker run {!s} {!s} ...".format(docker_image," ".join(publish)))
      out = dc.containers.run(docker_image,command=publish,volumes_from=['sunet-pages-api'],detach=False)
      logging.debug(out)
   else:
      buf = StringIO.StringIO()
      _p(publish, outf=buf)
      logging.debug(buf.getvalue())
      
def _site_update(stage_dir, pub_dir, name, config):
   logging.info("update called...")
   try:
      local_path = os.path.join(stage_dir, name)
      pub_path = os.path.join(pub_dir, name)

      _site_fetch(local_path, pub_path, config)
      _site_update_config(local_path, config)
      _site_publish(local_path, pub_path, config)
      _site_config(local_path, pub_dir, config)

      if 'domains' in config:
         _sync_links([os.path.join(pub_dir,domain) for domain in config['domains']], local_path, pub_dir)
   except Exception as err:
      logging.error(err)
      raise err

class StreamToLogger(object):
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

def _job_init():
   job_logger = logging.getLogger("worker")
   sys.stdout = StreamToLogger(job_logger, logging.INFO)
   sys.stderr = StreamToLogger(job_logger, logging.ERROR)
   
pool = Pool(5, _job_init)

@app.route("/notify/github", methods=['GET','POST'])
def _github_hook():
   info = request.get_json()
   if 'repository' not in info:
      raise BadRequest()

   logging.debug(info)
   repository = info['repository']
   logging.info("push to %s by %s" % (_name(repository),info['sender']['login']))
   configs = _find_config(repository)
   if configs:
      name,config = configs[0]
      res = pool.apply_async(_site_update, (stage_dir, pub_dir, name, config))
      logging.info("scheduled update of %s" % name)
      return jsonify(status="ok",name=name)
   raise NotFound()

@app.route("/notify/simple", methods=["GET","POST"])
def _simple_hook():
   global sites
   global auth_cookie
   info = request.get_json()
   if 'name' not in info:
      raise BadRequest()
   name = info['name']
   config = sites.get(name,None)
   if not config:
      raise BadRequest()
   if auth_cookie and not auth_cookie == info['auth']:
      raise Unauthorized()
   logging.info("simple notify to %s" % (info['name']))
   res = pool.apply_async(_site_update, (stage_dir, pub_dir, name, config))
   logging.info("scheduled update of %s" % name)
   return jsonify(status="ok",name=name)

def main():
    app.run(host='0.0.0.0')

if __name__ == "__main__":
    main()
