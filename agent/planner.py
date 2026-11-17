"""Rank bounded, interpretable hypotheses from a detected period shift."""
from __future__ import annotations


def generate_hypotheses(finding: dict) -> list[dict]:
    identifier = finding["id"]
    if identifier == "returns":
        choices = [("Fulfillment delay is concentrated in a category", "category"), ("A region or warehouse is contributing disproportionate returns", "region")]
    elif identifier in {"revenue", "basket-value"}:
        choices = [("Revenue decline is concentrated in a channel", "channel"), ("Product mix shifted within a category", "category")]
    else:
        choices = [("A segment contains a material change", "category")]
    return [{"hypothesis": text, "dimension": dimension, "rank": index + 1} for index, (text, dimension) in enumerate(choices)]
