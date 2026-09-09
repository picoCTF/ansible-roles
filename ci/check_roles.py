#!/usr/bin/env python3
"""Cheap structural checks for the roles in this repository.

Deliberately narrow. These catch mistakes that are invisible until a play runs
against a real host -- a template that does not parse, a variable wired into a
template but never given a default -- and nothing else. They are not a style
gate: ansible-lint runs separately and does not block, because the two largest
findings it reports (variable naming without a role prefix, and the yes/no
truthy idiom) are choices this repository made on purpose.

Exit status is 1 if any check fails.
"""
import glob
import os
import re
import sys

import yaml
from jinja2 import Environment, meta


class _AcceptAny(dict):
    """Jinja resolves filters and tests at compile time and fails on unknown
    names. Ansible supplies dozens (to_json, bool, ternary, default, ...) that
    plain Jinja does not, and this check is about variables, not filters, so
    every name is accepted and the value never used."""

    def __contains__(self, key):  # noqa: D105
        return True

    @staticmethod
    def _stub(*args, **kwargs):
        return ""

    def __getitem__(self, key):
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            return self._stub

    def get(self, key, default=None):
        # Jinja looks filters up with .get(), which bypasses __getitem__.
        return self[key]


def _env():
    env = Environment()
    env.filters = _AcceptAny(env.filters)
    env.tests = _AcceptAny(env.tests)
    return env

# Names a template may reference without this repository defining them.
#   ansible_* / inventory_hostname / groups: facts and inventory
#   ansible_managed: substituted by the template module itself
#   item / ansible_loop: loop scope
ALLOWED = {"item", "ansible_managed", "inventory_hostname", "groups", "ansible_loop"}
ALLOWED_PREFIX = ("ansible_",)

failures = []


def role_names(role):
    """Every variable name a role legitimately defines for its own templates."""
    names = set()
    for sub in ("defaults/main.yml", "vars/main.yml"):
        path = os.path.join("roles", role, sub)
        if os.path.exists(path):
            loaded = yaml.safe_load(open(path, encoding="utf-8")) or {}
            names |= set(loaded.keys())
    # set_fact and register introduce names the templates may use.
    for path in glob.glob("roles/%s/tasks/*.yml" % role):
        text = open(path, encoding="utf-8", errors="replace").read()
        for block in re.findall(r"set_fact:\s*\n((?:\s+\S+:.*\n)+)", text):
            names |= set(re.findall(r"^\s+([A-Za-z_][A-Za-z0-9_]*):", block, re.M))
        names |= set(re.findall(r"^\s*register:\s*(\S+)", text, re.M))
    return names


def check_yaml():
    for path in glob.glob("roles/**/*.yml", recursive=True) + glob.glob("*.yml"):
        try:
            yaml.safe_load(open(path, encoding="utf-8"))
        except Exception as exc:
            failures.append("YAML does not parse: %s: %s" % (path, exc))


def check_templates():
    env = _env()
    for role in sorted(os.listdir("roles")):
        known = role_names(role) | ALLOWED
        for path in sorted(glob.glob("roles/%s/templates/*" % role)):
            if not path.endswith(".j2"):
                continue
            text = open(path, encoding="utf-8", errors="replace").read()
            try:
                ast = env.parse(text)
            except Exception as exc:
                failures.append("template does not parse: %s: %s" % (path, exc))
                continue
            for name in sorted(meta.find_undeclared_variables(ast)):
                if name in known or name.startswith(ALLOWED_PREFIX):
                    continue
                failures.append(
                    "%s references '%s', which has no default, vars entry, "
                    "set_fact or register in role '%s'" % (path, name, role)
                )


check_yaml()
check_templates()

if failures:
    print("%d problem(s):\n" % len(failures))
    for line in failures:
        print("  " + line)
    sys.exit(1)
print("roles OK: YAML parses, templates parse, template variables all resolve")
