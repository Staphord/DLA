"""
runserver + FORCE_SCRIPT_NAME: WSGI PATH_INFO is the full URI path (/DLA/static/...).
Django then builds request.path as /DLA + / + DLA/static/... (double script name).
StaticFilesHandler matches on raw PATH_INFO but serve() slices request.path → wrong
relative path → 404. nginx usually sets PATH_INFO without the script prefix; dev server
does not, so we normalize PATH_INFO once and widen static URL detection.
"""
from __future__ import annotations


def _strip_force_script_prefix_from_environ(environ):
    from django.conf import settings

    script = getattr(settings, "FORCE_SCRIPT_NAME", None) or ""
    script = script.rstrip("/")
    if not script:
        return environ
    pi = environ.get("PATH_INFO") or ""
    if pi.startswith(script + "/") or pi == script:
        return {**environ, "PATH_INFO": pi[len(script):] or "/"}
    return environ


def _patched_should_handle(self, path):
    if self.base_url[1]:
        return False
    if path.startswith(self.base_url[2]):
        return True
    from django.conf import settings

    script = (getattr(settings, "FORCE_SCRIPT_NAME", None) or "").rstrip("/")
    static_path = self.base_url[2]
    if script and static_path.startswith(script + "/"):
        stripped_prefix = static_path[len(script) :]
        if path.startswith(stripped_prefix):
            return True
    return False


def apply():
    from django.contrib.staticfiles.handlers import StaticFilesHandler

    if getattr(StaticFilesHandler, "_rfq_force_script_patch_applied", False):
        return

    _orig_call = StaticFilesHandler.__call__

    def __call__(self, environ, start_response):
        environ = _strip_force_script_prefix_from_environ(environ)
        return _orig_call(self, environ, start_response)

    StaticFilesHandler.__call__ = __call__
    StaticFilesHandler._should_handle = _patched_should_handle
    StaticFilesHandler._rfq_force_script_patch_applied = True


def _scope_strip_root_path(scope):
    from django.conf import settings

    script = getattr(settings, "FORCE_SCRIPT_NAME", None) or ""
    script = script.rstrip("/")
    if not script or scope.get("type") != "http":
        return scope
    path = scope.get("path") or ""
    if path.startswith(script + "/") or path == script:
        new = dict(scope)
        new["path"] = path[len(script):] or "/"
        return new
    return scope


def apply_asgi():
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    if getattr(ASGIStaticFilesHandler, "_rfq_force_script_patch_applied", False):
        return

    _orig = ASGIStaticFilesHandler.__call__

    async def __call__(self, scope, receive, send):
        scope = _scope_strip_root_path(scope)
        return await _orig(self, scope, receive, send)

    ASGIStaticFilesHandler.__call__ = __call__
    ASGIStaticFilesHandler._should_handle = _patched_should_handle
    ASGIStaticFilesHandler._rfq_force_script_patch_applied = True
