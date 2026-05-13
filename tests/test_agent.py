"""
test_agent.py — Golden test runner for PRISM.

Runs 6 predefined golden test cases and validates:
  - status == SUCCESS
  - confidence label in expected set
  - root pattern in expected set
  - ORA code matches
  - causal chain contains expected pattern

Usage:
  python tests/test_agent.py
  python tests/test_agent.py --verbose
  python tests/test_agent.py --test TC-01
"""

from __future__ import annotations
import os
import sys
import json
import time
import argparse

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from src.agent.agent import OracleDiagnosticAgent


def load_test_cases(path: str = "tests/golden_test_cases.json") -> list[dict]:
    with open(path) as f:
        return json.load(f)


def run_test(agent: OracleDiagnosticAgent, tc: dict, verbose: bool = False) -> dict:
    """Run a single test case. Returns result dict."""
    inp = tc["input"]
    exp = tc["expected"]

    t0 = time.time()
    report = agent.diagnose(
        query=inp["query"],
        ora_code=inp.get("ora_code", ""),
        hostname=inp.get("hostname", ""),
        platform=inp.get("platform", "LINUX"),
    )
    elapsed_ms = (time.time() - t0) * 1000

    # ── Assertions ───────────────────────────────────────────────
    failures = []

    # 1. Status
    if report["status"] != exp["status"]:
        failures.append(f"status: got '{report['status']}' expected '{exp['status']}'")

    # 2. Confidence label
    if exp.get("confidence_label_in"):
        label = report["confidence"]["label"]
        if label not in exp["confidence_label_in"]:
            failures.append(f"confidence label: got '{label}' expected one of {exp['confidence_label_in']}")

    # 3. Root pattern
    if exp.get("root_pattern_in") and report["status"] == "SUCCESS":
        got_pattern = (report.get("root_cause") or {}).get("pattern", "")
        if got_pattern not in exp["root_pattern_in"]:
            failures.append(f"root_pattern: got '{got_pattern}' expected one of {exp['root_pattern_in']}")

    # 4. ORA code
    if exp.get("ora_code") and report["status"] == "SUCCESS":
        got_ora = (report.get("ora_code") or {}).get("code", "")
        if got_ora != exp["ora_code"]:
            failures.append(f"ora_code: got '{got_ora}' expected '{exp['ora_code']}'")

    # 5. Causal chain contains
    if exp.get("causal_chain_contains") and report["status"] == "SUCCESS":
        chain_str = " ".join(report.get("causal_chain", []))
        if exp["causal_chain_contains"] not in chain_str:
            failures.append(
                f"causal_chain: '{exp['causal_chain_contains']}' not found in chain {report.get('causal_chain')}"
            )

    passed = len(failures) == 0

    result = {
        "test_id":      tc["test_id"],
        "name":         tc["name"],
        "passed":       passed,
        "failures":     failures,
        "elapsed_ms":   round(elapsed_ms, 1),
        "confidence":   report["confidence"]["score"],
        "label":        report["confidence"]["label"],
        "root_pattern": (report.get("root_cause") or {}).get("pattern", "N/A"),
        "status":       report["status"],
    }

    if verbose:
        _print_verbose(result, report)

    return result


def _print_verbose(result: dict, report: dict):
    sep = "─" * 60
    icon = "✅" if result["passed"] else "❌"
    print(f"\n{sep}")
    print(f"{icon}  {result['test_id']}: {result['name']}")
    print(f"    Status:       {result['status']}")
    print(f"    Confidence:   {result['label']} ({result['confidence']}%)")
    print(f"    Root Pattern: {result['root_pattern']}")
    print(f"    Chain:        {' → '.join(report.get('causal_chain', []))}")
    print(f"    Time:         {result['elapsed_ms']}ms")
    if result["failures"]:
        for f in result["failures"]:
            print(f"    ✗ {f}")


def main():
    parser = argparse.ArgumentParser(description="PRISM — Golden Test Runner")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--test", "-t", help="Run a single test by ID (e.g. TC-01)")
    parser.add_argument("--json", "-j", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    print("\n🔍 PRISM — Golden Test Suite")
    print("=" * 60)
    print("Loading agent and BM25 index...")

    agent = OracleDiagnosticAgent()
    agent.initialize()
    print("Agent ready.\n")

    test_cases = load_test_cases()
    if args.test:
        test_cases = [tc for tc in test_cases if tc["test_id"] == args.test]
        if not test_cases:
            print(f"No test found with ID: {args.test}")
            sys.exit(1)

    results = []
    for tc in test_cases:
        if not args.verbose:
            print(f"  Running {tc['test_id']}: {tc['name']}...", end=" ", flush=True)
        result = run_test(agent, tc, verbose=args.verbose)
        results.append(result)
        if not args.verbose:
            icon = "✅" if result["passed"] else "❌"
            print(f"{icon}  ({result['label']} {result['confidence']}%)  {result['elapsed_ms']}ms")

    # ── Summary ──────────────────────────────────────────────────
    passed = sum(1 for r in results if r["passed"])
    total  = len(results)

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} passed")

    if passed == total:
        print("🎉 All golden tests PASSED!")
    else:
        print(f"⚠️  {total - passed} test(s) FAILED:")
        for r in results:
            if not r["passed"]:
                print(f"  ✗ {r['test_id']}: {r['name']}")
                for f in r["failures"]:
                    print(f"      {f}")

    avg_ms = sum(r["elapsed_ms"] for r in results) / len(results) if results else 0
    print(f"\nAverage processing time: {avg_ms:.1f}ms per query")

    if args.json:
        print("\n" + json.dumps(results, indent=2))

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
