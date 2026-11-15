from unittest.mock import patch

import pytest

from app import create_app, store


@pytest.fixture
def client():
    store.reset()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Task 2: Notification Integration Tests (Member A - Success Path)
# ---------------------------------------------------------------------------


def test_return_book_notifies_next_hold_member_mock(client):
    """Mock test: returning a book with an active hold calls send_notification once."""
    book_resp = client.post(
        "/books",
        json={"title": "Clean Architecture", "author": "Robert C. Martin", "isbn": "978-0134494166", "total_copies": 1},
    )
    book_id = book_resp.get_json()["id"]

    borrower = client.post("/members", json={"name": "Alice", "email": "alice@example.com"}).get_json()
    waiter = client.post("/members", json={"name": "Bob", "email": "bob@example.com"}).get_json()

    loan_resp = client.post("/loans", json={"book_id": book_id, "member_id": borrower["id"]})
    loan_id = loan_resp.get_json()["id"]

    hold_resp = client.post(f"/books/{book_id}/hold", json={"member_id": waiter["id"]})
    assert hold_resp.status_code == 201

    with patch("app.routes.loans.send_notification", return_value=True) as mock_send:
        ret_resp = client.put(f"/loans/{loan_id}/return")

    assert ret_resp.status_code == 200
    body = ret_resp.get_json()
    assert body["notified"] is True
    assert body["return_date"] is not None
    assert store.books[book_id].available_copies == 1
    assert store.books[book_id].holds == []

    mock_send.assert_called_once_with(
        "bob@example.com",
        "Hold Available",
        "Hello Bob, your hold for 'Clean Architecture' is now available for pickup.",
    )


def test_return_book_hold_notification_stub_success(client, monkeypatch):
    """Stub test: send_notification returning True clears the notified hold from queue."""
    book_id = client.post(
        "/books",
        json={"title": "Refactoring", "author": "Martin Fowler", "isbn": "978-0134757599", "total_copies": 1},
    ).get_json()["id"]

    borrower_id = client.post("/members", json={"name": "Carol", "email": "carol@example.com"}).get_json()["id"]
    first_waiter_id = client.post("/members", json={"name": "Dave", "email": "dave@example.com"}).get_json()["id"]
    second_waiter_id = client.post("/members", json={"name": "Eve", "email": "eve@example.com"}).get_json()["id"]

    loan_id = client.post("/loans", json={"book_id": book_id, "member_id": borrower_id}).get_json()["id"]
    client.post(f"/books/{book_id}/hold", json={"member_id": first_waiter_id})
    client.post(f"/books/{book_id}/hold", json={"member_id": second_waiter_id})

    monkeypatch.setattr(
        "app.routes.loans.send_notification",
        lambda recipient, subject, message: True,
    )

    ret_resp = client.put(f"/loans/{loan_id}/return")
    assert ret_resp.status_code == 200
    assert ret_resp.get_json()["notified"] is True
    assert store.books[book_id].holds == [second_waiter_id]


# ---------------------------------------------------------------------------
# Task 3: Coverage-Directed Tests (views.py, books.py, members.py)
# ---------------------------------------------------------------------------


def test_ui_home_and_books_workflow(client):
    """Covers home(), books_page() GET/POST, and delete_book_page() in views.py."""
    home_resp = client.get("/")
    assert home_resp.status_code == 200

    post_resp = client.post(
        "/ui/books",
        data={"title": "Design Patterns", "author": "GoF", "isbn": "978-0201633610", "total_copies": "2"},
    )
    assert post_resp.status_code == 302
    assert len(store.books) == 1

    get_resp = client.get("/ui/books")
    assert get_resp.status_code == 200
    assert b"Design Patterns" in get_resp.data

    book_id = next(iter(store.books.keys()))
    del_resp = client.post(f"/ui/books/{book_id}/delete")
    assert del_resp.status_code == 302
    assert len(store.books) == 0


def test_ui_members_and_loans_workflow(client):
    """Covers members_page(), delete_member_page(), loans_page(), and return_loan_page()."""
    mem_post = client.post(
        "/ui/members",
        data={"name": "Grace Hopper", "email": "grace@example.com"},
    )
    assert mem_post.status_code == 302
    assert len(store.members) == 1

    mem_get = client.get("/ui/members")
    assert mem_get.status_code == 200
    assert b"Grace Hopper" in mem_get.data

    client.post(
        "/ui/books",
        data={"title": "Compilers", "author": "Aho", "isbn": "978-0321486813", "total_copies": "1"},
    )
    book_id = next(iter(store.books.keys()))
    member_id = next(iter(store.members.keys()))

    loan_post = client.post(
        "/ui/loans",
        data={"book_id": str(book_id), "member_id": str(member_id)},
    )
    assert loan_post.status_code == 302
    assert len(store.loans) == 1
    assert store.books[book_id].available_copies == 0

    loan_get = client.get("/ui/loans")
    assert loan_get.status_code == 200

    loan_id = next(iter(store.loans.keys()))
    ret_post = client.post(f"/ui/loans/{loan_id}/return")
    assert ret_post.status_code == 302
    assert store.loans[loan_id].return_date is not None
    assert store.books[book_id].available_copies == 1

    del_mem = client.post(f"/ui/members/{member_id}/delete")
    assert del_mem.status_code == 302
    assert len(store.members) == 0


def test_books_search_and_error_branches(client):
    """Covers list_books search filter, 404s on update/delete, and hold validation errors."""
    created = client.post(
        "/books",
        json={"title": "Introduction to Algorithms", "author": "CLRS", "isbn": "978-0262046305", "total_copies": 1},
    ).get_json()
    book_id = created["id"]

    search_resp = client.get("/books?search=algorithms")
    assert search_resp.status_code == 200
    assert len(search_resp.get_json()) == 1

    assert client.put("/books/999", json={"title": "Missing"}).status_code == 404
    assert client.delete("/books/999").status_code == 404

    assert client.post("/books/999/hold", json={"member_id": 1}).status_code == 404
    assert client.post(f"/books/{book_id}/hold", json={}).status_code == 400
    assert client.post(f"/books/{book_id}/hold", json={"member_id": 999}).status_code == 400

    member_id = client.post("/members", json={"name": "Alan Turing", "email": "alan@example.com"}).get_json()["id"]
    assert client.post(f"/books/{book_id}/hold", json={"member_id": member_id}).status_code == 201
    assert client.post(f"/books/{book_id}/hold", json={"member_id": member_id}).status_code == 400


def test_members_not_found_branches(client):
    """Covers 404 branches in get_member, update_member, and delete_member."""
    assert client.get("/members/999").status_code == 404
    assert client.put("/members/999", json={"name": "Nobody"}).status_code == 404
    assert client.delete("/members/999").status_code == 404