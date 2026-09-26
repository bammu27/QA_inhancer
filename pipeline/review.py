"""
Unit 6 — QA Review Gate
Pure decision recording: given a button click, return True (approve)
or False (cancel). No UI, no network, no state — all of that lives in
app.py per the pattern established across all prior units.
"""


def review_and_approve(decision: str) -> bool:
    """
    Args:
        decision: exactly "approve" or "cancel" — the tester's button
                   click, passed in by app.py. This function does not
                   render UI itself (Streamlit buttons live in app.py,
                   per the pattern established in every prior unit) — it
                   is the pure decision-recording step, called once per
                   click.

    Returns:
        True if decision == "approve", False if decision == "cancel".

    Raises:
        ValueError: if decision is anything other than "approve" or
            "cancel" — a caller bug, since app.py only ever passes one of
            these two literals.
    """
    if decision == "approve":
        return True
    elif decision == "cancel":
        return False
    else:
        raise ValueError(f'review_and_approve received invalid decision: "{decision}"')
