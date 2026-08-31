"""
Helper script to parse and format pytest junit.xml test failures in CI.
"""

import os
import sys
import xml.etree.ElementTree as ET


def main():
    xml_path = sys.argv[1] if len(sys.argv) > 1 else "junit.xml"
    try:
        tree = ET.parse(xml_path)
    except Exception as e:
        print(f"Could not parse {xml_path}: {e}")
        return

    failures = []
    for tc in tree.iter("testcase"):
        fail_node = tc.find("failure")
        err_node = tc.find("error")
        node = fail_node if fail_node is not None else err_node
        if node is not None:
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            msg = node.get("message", "")
            text = node.text or ""
            failures.append((classname, name, msg, text))

    print("\n=======================================================")
    print(f"TOTAL FAILED TESTS: {len(failures)}")
    print("=======================================================")
    for cname, name, msg, text in failures:
        print(f"\n[FAIL] {cname}::{name}")
        if msg:
            print(f"  Message: {msg}")
        if text:
            print(f"  Traceback:\n{text.strip()}")
        # Emit GitHub Actions workflow annotation error
        short_err = msg or (text.strip().split("\n")[-1] if text else "Test failed")
        print(f"::error title={cname}::{name}::{short_err}")
    print("=======================================================\n")

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file and failures:
        try:
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(f"### ❌ Pytest Failures ({len(failures)})\n\n")
                for cname, name, msg, text in failures:
                    f.write(f"- **`{cname}::{name}`**\n")
                    if msg:
                        f.write(f"  > {msg}\n\n")
                    if text:
                        f.write(f"```text\n{text[:1000]}\n```\n\n")
        except Exception as e:
            print(f"Error writing step summary: {e}")


if __name__ == "__main__":
    main()
