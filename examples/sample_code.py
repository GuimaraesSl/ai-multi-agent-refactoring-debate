"""Example module with intentional smells spanning all three quality dimensions.

Run the debate over it::

    uv run refactoring-debate examples/sample_code.py
    uv run refactoring-debate examples/sample_code.py --dynamic     # also profile/measure energy
"""

import os  # noqa: F401  (intentional: unused import = architectural smell)
import json  # noqa: F401  (intentional: unused import = architectural smell)


def find_duplicates(items):
    # Quadratic scan: a performance bottleneck AND a sustainability (energy) green smell.
    duplicates = []
    for i in range(len(items)):
        for j in range(len(items)):
            if i != j and items[i] == items[j]:
                if items[i] not in duplicates:
                    duplicates.append(items[i])
    return duplicates


def summarize(records, threshold, prefix, suffix, separator, include_header):
    # Long function with too many parameters and deep nesting.
    lines = []
    if include_header:
        lines.append(prefix + "REPORT" + suffix)
    for record in records:
        if record.get("value", 0) > threshold:
            if record.get("active"):
                if record.get("tags"):
                    for tag in record["tags"]:
                        lines.append(prefix + str(tag) + separator + str(record["value"]) + suffix)
                else:
                    lines.append(prefix + "untagged" + suffix)
    return separator.join(lines)


class ReportManager:
    """A god class: too many unrelated responsibilities (low cohesion)."""

    def __init__(self, data):
        self.data = data

    def load(self): ...
    def save(self): ...
    def validate(self): ...
    def transform(self): ...
    def render_html(self): ...
    def render_pdf(self): ...
    def send_email(self): ...
    def archive(self): ...

    def analyze(self):
        return find_duplicates(self.data)


if __name__ == "__main__":
    # A small workload so the dynamic tools (Scalene/cProfile/CodeCarbon) have something to measure.
    sample = [i % 50 for i in range(1500)]
    print("duplicates:", len(find_duplicates(sample)))
    records = [
        {"value": i, "active": i % 2 == 0, "tags": ["a", "b"] if i % 3 == 0 else []}
        for i in range(200)
    ]
    print(summarize(records, threshold=10, prefix="- ", suffix="", separator="\n", include_header=True)[:40])
