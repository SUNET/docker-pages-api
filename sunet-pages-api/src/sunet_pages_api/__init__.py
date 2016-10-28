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

from werkzeug.exceptions import BadRequest
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

def _clone_url(r):
   return r['clone_url']

def _name(r):
   return r['full_name']

def _find_config(r):
   global sites
   return [(name,config) for name,config in sites.iteritems() if 'git' in config and _clone_url(r) == config['git']]

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
   pub_conf = os.path.join(local_path,".sunetpages.yaml")
   if os.path.exists(pub_conf):
      with open(pub_conf) as fd:
         cfg = yaml.load(fd)
         config.update(cfg)
 
def _pstart(args, outf=None, ignore_exit=False):
    env = {}
    logging.debug(" ".join(args))
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return proc


def _p(args, outf=None, ignore_exit=False):
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
    rv = proc.wait()
    if rv and not ignore_exit:
        raise RuntimeError("command exited with code != 0: %d" % rv)

def _site_publish(local_path, pub_path, config):
   local_path = local_path.rstrip("/")
   pub_path = pub_path.rstrip("/")
   publish = config.get('publish', ['rsync','--exclude=.git','--delete','-az', "%s/" % local_path, "%s/" % pub_path])
   docker_image = config.get('docker', None)
   buf = StringIO.StringIO()
   if docker_image is not None:
      _p("docker pull %s" % docker_image, outf=buf)
      logger.debug(buf.getvalue())
      publish = ['docker', 'run', docker_image] + publish

   _p(publish, outf=buf)
   logger.debug(buf.getvalue())
      
def _site_update(stage_dir, pub_dir, name, config):
   logging.info("update called...")
   local_path = os.path.join(stage_dir, name)
   pub_path = os.path.join(pub_dir, name)

   _site_fetch(local_path, pub_path, config)
   _site_update_config(local_path, config)
   _site_publish(local_path, pub_path, config)
   _site_config(local_path, pub_dir, config)

   if 'domains' in config:
      _sync_links([os.path.join(pub_dir,domain) for domain in config['domains']], local_path, pub_dir)

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


def main():
    app.run(host='0.0.0.0')

if __name__ == "__main__":
    main()
