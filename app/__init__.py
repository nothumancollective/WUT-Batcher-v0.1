from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path


class _PycCacheFinder(importlib.abc.MetaPathFinder):
    def __init__(self, package: str, package_root: Path) -> None:
        self._package = package
        self._package_root = package_root

    def find_spec(self, fullname: str, path: object | None, target: object | None = None):
        if fullname == self._package:
            return None

        if not fullname.startswith(f"{self._package}."):
            return None

        cache_tag = sys.implementation.cache_tag
        rel_parts = fullname.split(".")[1:]
        module_dir = self._package_root.joinpath(*rel_parts[:-1])
        module_name = rel_parts[-1]

        # Prefer real source files when present (we may reconstruct missing modules after recovery).
        source_path = module_dir / f"{module_name}.py"
        if source_path.is_file():
            return None

        # Module bytecode (e.g. app/__pycache__/cli.cpython-312.pyc)
        pyc_path = module_dir / "__pycache__" / f"{module_name}.{cache_tag}.pyc"
        if pyc_path.is_file():
            # Only load bytecode compatible with the current interpreter (recovery can corrupt headers).
            if pyc_path.read_bytes()[:4] != importlib.util.MAGIC_NUMBER:
                return None

            virtual_py = module_dir / f"{module_name}.py"
            loader = importlib.machinery.SourcelessFileLoader(fullname, str(pyc_path))
            spec = importlib.util.spec_from_file_location(
                fullname,
                location=str(virtual_py),
                loader=loader,
            )
            if spec is not None:
                spec.cached = str(pyc_path)
            return spec

        # Package bytecode (e.g. app/subpkg/__pycache__/__init__.cpython-312.pyc)
        pkg_dir = module_dir / module_name
        if (pkg_dir / "__init__.py").is_file():
            return None

        init_pyc = pkg_dir / "__pycache__" / f"__init__.{cache_tag}.pyc"
        if init_pyc.is_file():
            if init_pyc.read_bytes()[:4] != importlib.util.MAGIC_NUMBER:
                return None

            virtual_init = pkg_dir / "__init__.py"
            loader = importlib.machinery.SourcelessFileLoader(fullname, str(init_pyc))
            spec = importlib.util.spec_from_file_location(
                fullname,
                location=str(virtual_init),
                loader=loader,
                submodule_search_locations=[str(pkg_dir)],
            )
            if spec is not None:
                spec.cached = str(init_pyc)
            return spec

        return None


_FINDER_SENTINEL = object()


def _install_pyc_cache_finder() -> None:
    if getattr(sys, "_batch_software_pyc_cache_finder", _FINDER_SENTINEL) is not _FINDER_SENTINEL:
        return

    package_root = Path(__file__).resolve().parent
    sys.meta_path.insert(0, _PycCacheFinder(package="app", package_root=package_root))
    sys._batch_software_pyc_cache_finder = True  # type: ignore[attr-defined]


_install_pyc_cache_finder()
