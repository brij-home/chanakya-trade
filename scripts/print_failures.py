"""
Helper script to parse and format pytest junit.xml test failures in CI.
"""

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
    print("=======================================================\n")


if __name__ == "__main__":
    main()
