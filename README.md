sunet pages
====

A simple github-driven (mostly) static web platform.

This is mostly a github webhook endpoint that pulls public repositories and generates a website from it - much like github pages but on your own infrastructure. Configuration is in /etc/sunet-pages.yaml:

```yaml
---
a.site.name:
   git: https://github.com/the/repo.git
   domains:
      - an.alias.io
another.site
   git: https://github.com/another/repo.git
   branch: production
   docker: docker.example.com/site_generator
   publish: 
       - generate
```

Sites are staged and inspected for a secondary yaml file in the root of the repository called .sunet-pages.yaml which is loaded into the above configuration for the site matching the git repo URL in the github notification. The first example above would just make the content in the repo available (except the .git directory) in /usr/local/apache2/vhosts/a.site.name (with a link from an.alias.io). The directory layout is suitable for use with mod_vhost_alias. The second example would run the command

```bash
# docker run docker.example.com/site_generator generate <staging_dir> /usr/local/apache2/vhosts/another.site/
```

If the 'docker' key is omitted the command is executed in the sunet-pages-api container which is probably not what you want unless your site generator is directly included in the api container.
