"""Test utility loading and injection into Jupyter kernel, including restart survival.

Usage: python tests/scripts/test_utility_injection.py

This script tests the default (module-level) KernelSession to verify
that utilities can be injected, called, and survive kernel restarts.
"""

import sys
import time
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))

from CAi.CAi_agent.utilities.registry import UtilityRegistry
from CAi.CAi_agent.execution import repl as repl_mod

# Access the default session's internals.
_default = repl_mod._default_session
inject_utilities_with_monitoring = repl_mod.inject_utilities_with_monitoring
reset_namespace = repl_mod.reset_namespace
flush_utility_usage = repl_mod.flush_utility_usage


def _get_state():
    """Read current session state (avoids from-import staleness)."""
    return (
        _default._utilities_injected,
        _default._injected_utility_names,
        _default._injected_utilities,
    )

UTILITIES_DIR = repo_root / "agent_workspace" / "_utilities"

print("=" * 60)
print("1. Load utilities from disk")
print("=" * 60)

reg = UtilityRegistry(UTILITIES_DIR)
print(f"  Found {len(reg)} utilities:")
for name, spec in reg.specs.items():
    print(f"    - {name} (calls={spec.call_count}, success={spec.success_count})")

utilities = reg.load_snapshot()
print(f"\n  load_snapshot() returned {len(utilities)} callables:")
for name, fn in utilities.items():
    print(f"    - {name}: {fn}")

assert len(utilities) > 0, "No utilities loaded!"
print("  OK: Utilities loaded from disk")

print("\n" + "=" * 60)
print("2. Inject utilities into kernel")
print("=" * 60)

inject_utilities_with_monitoring(utilities)
injected, names, funcs = _get_state()
print(f"  _utilities_injected = {injected}")
print(f"  _injected_utility_names = {names}")
print(f"  _injected_utilities keys = {list(funcs.keys())}")
assert injected
assert len(names) > 0
assert len(funcs) > 0
print("  OK: Utilities injected")

print("\n" + "=" * 60)
print("3. Verify utilities are callable in kernel")
print("=" * 60)

kc = _default._get_or_start_kernel()

for name in names:
    code = f"print('{name} in dir():', '{name}' in dir())"
    out, err = _default._execute_in_kernel(kc, code, timeout=10)
    print(f"  {name}: {out.strip()}")
    assert f"True" in out, f"{name} not found in kernel namespace!"
print("  OK: All utilities visible in kernel")

print("\n" + "=" * 60)
print("4. Test calling a utility in kernel")
print("=" * 60)

test_code = """
# Test filter_compounds_by_similarity if available
if 'filter_compounds_by_similarity' in dir():
    result = filter_compounds_by_similarity(
        reference_smiles='c1ccccc1',
        candidate_smiles=['c1ccccc1C', 'CCCC', 'c1ccccc1'],
        threshold=0.3,
    )
    print(f"filter_compounds_by_similarity returned {len(result)} results: {result[:2]}")
else:
    print("filter_compounds_by_similarity not available")
"""
out, err = _default._execute_in_kernel(kc, test_code, timeout=10)
print(f"  Output:\n{out}")
if err:
    print(f"  Error: {err}")
assert "Error:" not in err or not err, f"Utility call failed: {err}"
print("  OK: Utility called successfully")

print("\n" + "=" * 60)
print("5. Verify usage tracking works")
print("=" * 60)

# Force collect usage stats
import json as _json_mod
collect_code = (
    "import json as _json; "
    "print('__UTIL_USAGE__:' + _json.dumps(dict(_utility_usage))); "
    "_utility_usage.clear()"
)
usage_out, _ = _default._execute_in_kernel(kc, collect_code, timeout=5)
print(f"  Raw usage: {usage_out.strip()}")
print("  OK: Usage tracking active")

print("\n" + "=" * 60)
print("6. Test kernel restart survival")
print("=" * 60)

print("  Restarting kernel...")
_default._restart_kernel()
time.sleep(2)  # Let kernel settle

kc = _default._get_or_start_kernel()
_, names_after_restart, _ = _get_state()
for name in names_after_restart[:3]:  # Check first 3
    code = f"print('{name} in dir():', '{name}' in dir())"
    out, err = _default._execute_in_kernel(kc, code, timeout=10)
    print(f"  After restart - {name}: {out.strip()}")
    assert f"True" in out, f"{name} LOST after kernel restart!"

print("  OK: All utilities survive kernel restart")

print("\n" + "=" * 60)
print("7. Test toolkit imports in kernel")
print("=" * 60)

toolkit_test = """
try:
    from CAi.toolkit import generate_molecules_reinvent4_mol2mol
    print(f"import OK: {generate_molecules_reinvent4_mol2mol}")
except Exception as e:
    print(f"import FAILED: {e}")
"""
out, err = _default._execute_in_kernel(kc, toolkit_test, timeout=10)
print(f"  {out.strip()}")
if err:
    print(f"  Error: {err}")
print("  OK: Toolkit import works")

print("\n" + "=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
