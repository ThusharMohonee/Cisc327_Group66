"""Assignment 3 tests - Member B (Bevin).

Task 2: hold-available notification, failure and non-trigger paths.
Task 3: coverage-directed tests for app/routes/loans.py and
        app/routes/reservations.py.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

import notification_service
from app import create_app, store
from app.models.loan import LOAN_PERIOD_DAYS


@pytest.fixture
def client():
    store.reset()
    notification_service.clear_notifications()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client
    store.reset()
    notification_service.clear_notifications()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_book(client, title="Dune", total_copies=1):
    resp = client.post(
        "/books",
        json={"title": title, "author": "Frank Herbert", "isbn": "978-0441013593",
              "total_copies": total_copies},
    )
    return resp.get_json()["id"]


def make_member(client, name, email):
    return client.post("/members", json={"name": name, "email": email}).get_json()["id"]


def checkout(client, book_id, member_id):
    return client.post("/loans", json={"book_id": book_id, "member_id": member_id}).get_json()["id"]


def loaned_book_with_hold(client):
    """A book that is checked out by one member and held by another."""
    book_id = make_book(client)
    borrower_id = make_member(client, "Alice", "alice@example.com")
    waiter_id = make_member(client, "Bob", "bob@example.com")
    loan_id = checkout(client, book_id, borrower_id)
    assert client.post(f"/books/{book_id}/hold", json={"member_id": waiter_id}).status_code == 201
    return book_id, loan_id, waiter_id


# ---------------------------------------------------------------------------
# Task 2: Notification tests - failure and non-trigger paths (Member B)
# ---------------------------------------------------------------------------


def test_return_succeeds_when_notification_fails_stub(client, monkeypatch):
    """Stub returns False: the return still succeeds, the response reports
    notified=False, and the member keeps their place in the hold queue."""
    book_id, loan_id, waiter_id = loaned_book_with_hold(client)
    monkeypatch.setattr("app.routes.loans.send_notification",
                        lambda recipient, subject, message: False)  # stub

    resp = client.put(f"/loans/{loan_id}/return")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["notified"] is False
    assert body["return_date"] == date.today().isoformat()
    assert store.loans[loan_id].return_date == date.today()
    assert store.books[book_id].available_copies == 1
    assert store.books[book_id].holds == [waiter_id]


def test_failed_notification_is_retried_on_next_return_stub(client, monkeypatch):
    """Stub returns False: because the hold is kept, the same member is first
    in line again when the next copy is returned."""
    book_id = make_book(client, total_copies=2)
    a = make_member(client, "Alice", "alice@example.com")
    b = make_member(client, "Bob", "bob@example.com")
    waiter_id = make_member(client, "Cara", "cara@example.com")
    loan1 = checkout(client, book_id, a)
    loan2 = checkout(client, book_id, b)
    client.post(f"/books/{book_id}/hold", json={"member_id": waiter_id})

    monkeypatch.setattr("app.routes.loans.send_notification",
                        lambda recipient, subject, message: False)
    assert client.put(f"/loans/{loan1}/return").get_json()["notified"] is False

    with patch("app.routes.loans.send_notification", return_value=True) as mock_send:
        resp = client.put(f"/loans/{loan2}/return")

    assert resp.get_json()["notified"] is True
    assert store.books[book_id].holds == []
    assert store.books[book_id].available_copies == 2
    assert mock_send.call_args.args[0] == "cara@example.com"


def test_return_without_holds_sends_no_notification_mock(client):
    """Mock: no one is waiting, so send_notification must not be called."""
    book_id = make_book(client)
    member_id = make_member(client, "Alice", "alice@example.com")
    loan_id = checkout(client, book_id, member_id)

    with patch("app.routes.loans.send_notification") as mock_send:
        resp = client.put(f"/loans/{loan_id}/return")

    assert resp.status_code == 200
    assert resp.get_json()["notified"] is False
    assert store.books[book_id].available_copies == 1
    mock_send.assert_not_called()


def test_hold_for_deleted_member_sends_no_notification_mock(client):
    """Mock: the held member no longer exists, so no notification is sent
    and the return still completes."""
    book_id, loan_id, waiter_id = loaned_book_with_hold(client)
    assert client.delete(f"/members/{waiter_id}").status_code == 204

    with patch("app.routes.loans.send_notification") as mock_send:
        resp = client.put(f"/loans/{loan_id}/return")

    assert resp.status_code == 200
    assert resp.get_json()["notified"] is False
    assert store.loans[loan_id].return_date is not None
    assert store.books[book_id].available_copies == 1
    mock_send.assert_not_called()


def test_returning_already_returned_loan_sends_no_notification_mock(client):
    """Mock: a second return is rejected before any notification logic runs."""
    book_id, loan_id, _ = loaned_book_with_hold(client)
    with patch("app.routes.loans.send_notification", return_value=True):
        client.put(f"/loans/{loan_id}/return")

    with patch("app.routes.loans.send_notification") as mock_send:
        resp = client.put(f"/loans/{loan_id}/return")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Loan already returned"
    assert store.books[book_id].available_copies == 1  # not incremented twice
    mock_send.assert_not_called()


def test_service_outage_records_nothing_stub(client, monkeypatch):
    """Stub the simulator's availability check (outage). The real
    send_notification then returns False and records nothing."""
    book_id, loan_id, waiter_id = loaned_book_with_hold(client)
    monkeypatch.setattr("notification_service.is_service_available", lambda: False)

    resp = client.put(f"/loans/{loan_id}/return")

    assert resp.status_code == 200
    assert resp.get_json()["notified"] is False
    assert store.books[book_id].holds == [waiter_id]
    assert notification_service.get_notifications() == []


# ---------------------------------------------------------------------------
# Task 3: Coverage-directed tests - app/routes/loans.py
# ---------------------------------------------------------------------------


def test_checkout_missing_book_returns_404(client):
    member_id = make_member(client, "Alice", "alice@example.com")
    resp = client.post("/loans", json={"book_id": 999, "member_id": member_id})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Book not found"
    assert store.loans == {}


def test_return_missing_loan_returns_404(client):
    resp = client.put("/loans/999/return")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Loan not found"


def test_list_loans_filter_by_book_id(client):
    book1 = make_book(client, "Dune")
    book2 = make_book(client, "Emma")
    member_id = make_member(client, "Alice", "alice@example.com")
    loan1 = checkout(client, book1, member_id)
    checkout(client, book2, member_id)

    resp = client.get(f"/loans?book_id={book1}")

    assert resp.status_code == 200
    assert [l["id"] for l in resp.get_json()] == [loan1]


@pytest.mark.xfail(reason="Defect: list_loans compares l.book_id to member_id, "
                          "so ?member_id= returns the wrong loans (R14)", strict=True)
def test_list_loans_filter_by_member_id(client):
    # Ids are chosen so the member id equals a different book's id:
    # member 1 borrows book 2, member 2 borrows book 1.
    book1 = make_book(client, "Dune")
    book2 = make_book(client, "Emma")
    alice = make_member(client, "Alice", "alice@example.com")
    bob = make_member(client, "Bob", "bob@example.com")
    alice_loan = checkout(client, book2, alice)
    checkout(client, book1, bob)

    resp = client.get(f"/loans?member_id={alice}")

    assert resp.status_code == 200
    assert [l["id"] for l in resp.get_json()] == [alice_loan]


def test_renew_extends_due_date_by_loan_period(client):
    book_id = make_book(client)
    member_id = make_member(client, "Alice", "alice@example.com")
    loan_id = checkout(client, book_id, member_id)
    original_due = store.loans[loan_id].due_date

    resp = client.put(f"/loans/{loan_id}/renew")

    expected = original_due + timedelta(days=LOAN_PERIOD_DAYS)
    assert resp.status_code == 200
    assert resp.get_json()["due_date"] == expected.isoformat()
    assert store.loans[loan_id].due_date == expected


def test_renew_missing_loan_returns_404(client):
    resp = client.put("/loans/999/renew")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Loan not found"


def test_renew_returned_loan_is_rejected(client):
    book_id = make_book(client)
    member_id = make_member(client, "Alice", "alice@example.com")
    loan_id = checkout(client, book_id, member_id)
    client.put(f"/loans/{loan_id}/return")
    due_before = store.loans[loan_id].due_date

    resp = client.put(f"/loans/{loan_id}/renew")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Loan already returned"
    assert store.loans[loan_id].due_date == due_before


@pytest.mark.xfail(reason="Defect: renew_loan does not check the book's hold queue, "
                          "so a loan can be renewed while someone is waiting (R20)", strict=True)
def test_renew_rejected_when_another_member_is_waiting(client):
    book_id, loan_id, _ = loaned_book_with_hold(client)
    due_before = store.loans[loan_id].due_date

    resp = client.put(f"/loans/{loan_id}/renew")

    assert resp.status_code == 400
    assert store.loans[loan_id].due_date == due_before


def test_fine_is_zero_when_not_overdue(client):
    book_id = make_book(client)
    member_id = make_member(client, "Alice", "alice@example.com")
    loan_id = checkout(client, book_id, member_id)

    resp = client.get(f"/loans/{loan_id}/fine")

    assert resp.status_code == 200
    assert resp.get_json() == {"loan_id": loan_id, "fine_amount": 0}


def test_fine_is_zero_on_due_date_boundary(client):
    book_id = make_book(client)
    member_id = make_member(client, "Alice", "alice@example.com")
    loan_id = checkout(client, book_id, member_id)
    store.loans[loan_id].due_date = date.today()

    assert client.get(f"/loans/{loan_id}/fine").get_json()["fine_amount"] == 0


def test_fine_for_active_overdue_loan(client):
    book_id = make_book(client)
    member_id = make_member(client, "Alice", "alice@example.com")
    loan_id = checkout(client, book_id, member_id)
    store.loans[loan_id].due_date = date.today() - timedelta(days=10)

    resp = client.get(f"/loans/{loan_id}/fine")

    assert resp.status_code == 200
    assert resp.get_json()["fine_amount"] == 2.5  # 10 days x $0.25


def test_fine_missing_loan_returns_404(client):
    resp = client.get("/loans/999/fine")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Loan not found"


@pytest.mark.xfail(reason="Defect: get_fine always uses date.today() instead of "
                          "loan.return_date, so a returned loan's fine keeps growing", strict=True)
def test_fine_is_fixed_at_return_date(client):
    book_id = make_book(client)
    member_id = make_member(client, "Alice", "alice@example.com")
    loan_id = checkout(client, book_id, member_id)
    loan = store.loans[loan_id]
    loan.due_date = date.today() - timedelta(days=10)
    loan.return_date = date.today() - timedelta(days=6)  # returned 4 days late

    resp = client.get(f"/loans/{loan_id}/fine")

    assert resp.get_json()["fine_amount"] == 1.0  # 4 days x $0.25


# ---------------------------------------------------------------------------
# Task 3: Coverage-directed tests - app/routes/reservations.py
# ---------------------------------------------------------------------------


def test_create_reservation_success(client):
    book_id = make_book(client)
    member_id = make_member(client, "Alice", "alice@example.com")

    resp = client.post("/reservations", json={"book_id": book_id, "member_id": member_id})

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["book_id"] == book_id
    assert body["member_id"] == member_id
    assert body["fulfilled"] is False
    assert body["reservation_date"] == date.today().isoformat()
    assert body["id"] in store.reservations


def test_create_reservation_missing_book_returns_404(client):
    member_id = make_member(client, "Alice", "alice@example.com")
    resp = client.post("/reservations", json={"book_id": 999, "member_id": member_id})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Book not found"
    assert store.reservations == {}


def test_create_reservation_missing_member_returns_404(client):
    book_id = make_book(client)
    resp = client.post("/reservations", json={"book_id": book_id, "member_id": 999})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Member not found"
    assert store.reservations == {}


def test_list_reservations_empty(client):
    resp = client.get("/reservations")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_list_reservations_filters_by_book_and_member(client):
    book1 = make_book(client, "Dune")
    book2 = make_book(client, "Emma")
    alice = make_member(client, "Alice", "alice@example.com")
    bob = make_member(client, "Bob", "bob@example.com")
    r1 = client.post("/reservations", json={"book_id": book1, "member_id": alice}).get_json()["id"]
    r2 = client.post("/reservations", json={"book_id": book2, "member_id": alice}).get_json()["id"]
    r3 = client.post("/reservations", json={"book_id": book1, "member_id": bob}).get_json()["id"]

    all_ids = [r["id"] for r in client.get("/reservations").get_json()]
    by_book = [r["id"] for r in client.get(f"/reservations?book_id={book1}").get_json()]
    by_member = [r["id"] for r in client.get(f"/reservations?member_id={alice}").get_json()]
    both = [r["id"] for r in client.get(
        f"/reservations?book_id={book1}&member_id={bob}").get_json()]

    assert all_ids == [r1, r2, r3]
    assert by_book == [r1, r3]
    assert by_member == [r1, r2]
    assert both == [r3]
