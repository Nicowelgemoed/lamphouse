"""Put your name and GitHub user into every credit, then rebuild Answer Print and Lamphouse.

  python set_author.py "Your Full Name" [your-github-user]
"""
import os, sys, glob
import config

name = sys.argv[1]
user = sys.argv[2] if len(sys.argv) > 2 else None
files = [os.path.join(config.HERE, 'config.py')] + [
    p for pat in ('*.md', '*.txt', 'docs/*.md') for p in glob.glob(os.path.join(config.REPO, pat))]
for p in files:
    s = open(p, encoding='utf-8').read()
    t = s.replace('@@AUTHOR@@', name)
    if user:
        t = t.replace('@@GITHUB_USER@@', user)
    if t != s:
        open(p, 'w', encoding='utf-8').write(t)
        print('updated', os.path.relpath(p, config.REPO))

import importlib
importlib.reload(config)
import export
export.build(0.03, config.OUT_STANDALONE)
export.build_lamphouse(config.OUT_LAMPHOUSE)
print('rebuilt', os.path.relpath(config.OUT_STANDALONE, config.REPO), 'and', os.path.relpath(config.OUT_LAMPHOUSE, config.REPO))
