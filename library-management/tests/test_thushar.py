import pytest

# --- BOOK ENDPOINT TESTS ---

def test_create_book_success(client):
    """Test POST /books creates a book with valid data (R1, R10, R37)."""
    response = client.post("/books", json={
        "title": "Software Engineering Principles",
        "author": "Ian Sommerville",
        "isbn": "978-0133943030",
        "total_copies": 5
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data["title"] == "Software Engineering Principles"
    assert data["available_copies"] == 5

def test_list_all_books(client):
    """Test GET /books retrieves created books (R1, R2, R13)."""
    client.post("/books", json={
        "title": "Clean Code",
        "author": "Robert C. Martin",
        "isbn": "978-0132350884",
        "total_copies": 3
    })
    response = client.get("/books")
    assert response.status_code == 200
    books = response.get_json()
    assert len(books) >= 1
    assert any(b["title"] == "Clean Code" for b in books)

def test_get_one_book(client):
    """Test GET /books/<id> retrieves specific book details (R1, R13)."""
    res = client.post("/books", json={
        "title": "Design Patterns",
        "author": "Erich Gamma",
        "isbn": "978-0201633610",
        "total_copies": 2
    })
    book_id = res.get_json()["id"]

    response = client.get(f"/books/{book_id}")
    assert response.status_code == 200
    assert response.get_json()["title"] == "Design Patterns"

def test_update_book(client):
    """Test PUT /books/<id> updates book details (R14, R30)."""
    res = client.post("/books", json={
        "title": "Refactoring",
        "author": "Martin Fowler",
        "isbn": "978-0201485677",
        "total_copies": 1
    })
    book_id = res.get_json()["id"]

    update_res = client.put(f"/books/{book_id}", json={"total_copies": 4})
    assert update_res.status_code == 200
    assert update_res.get_json()["total_copies"] == 4

def test_delete_book(client):
    """Test DELETE /books/<id> removes a book record (R30)."""
    res = client.post("/books", json={
        "title": "Legacy Code",
        "author": "Michael Feathers",
        "isbn": "978-0131177055",
        "total_copies": 1
    })
    book_id = res.get_json()["id"]

    del_res = client.delete(f"/books/{book_id}")
    assert del_res.status_code in (200, 204)
    
    get_res = client.get(f"/books/{book_id}")
    assert get_res.status_code == 404


# --- MEMBER ENDPOINT TESTS ---

def test_create_member_success(client):
    """Test POST /members creates a member without passwords (R21, R36)."""
    response = client.post("/members", json={
        "name": "Alice Smith",
        "email": "alice@example.com"
    })
    assert response.status_code == 201
    member = response.get_json()
    assert member["name"] == "Alice Smith"
    assert "id" in member

def test_list_all_members(client):
    """Test GET /members retrieves member directory (R1, R2, R21)."""
    client.post("/members", json={"name": "Bob Jones", "email": "bob@example.com"})
    response = client.get("/members")
    assert response.status_code == 200
    members = response.get_json()
    assert len(members) >= 1

def test_get_one_member(client):
    """Test GET /members/<id> retrieves member account profile (R1, R5, R21)."""
    res = client.post("/members", json={"name": "Charlie Brown", "email": "charlie@example.com"})
    member_id = res.get_json()["id"]

    response = client.get(f"/members/{member_id}")
    assert response.status_code == 200
    assert response.get_json()["name"] == "Charlie Brown"

def test_update_member(client):
    """Test PUT /members/<id> updates member contact info (R36)."""
    res = client.post("/members", json={"name": "Dave Miller", "email": "dave@old.com"})
    member_id = res.get_json()["id"]

    update_res = client.put(f"/members/{member_id}", json={"email": "dave@new.com"})
    assert update_res.status_code == 200
    assert update_res.get_json()["email"] == "dave@new.com"

def test_delete_member(client):
    """Test DELETE /members/<id> removes a member profile (R36)."""
    res = client.post("/members", json={"name": "Eve Adams", "email": "eve@example.com"})
    member_id = res.get_json()["id"]

    del_res = client.delete(f"/members/{member_id}")
    assert del_res.status_code in (200, 204)


# --- LOAN ENDPOINT TESTS & WORKFLOWS ---

def test_checkout_and_return_workflow(client):
    """Test complete borrowing workflow: checkout reduces copies, return restores (R4, R8, R11)."""
    b_res = client.post("/books", json={"title": "Test Driven Development", "author": "Kent Beck", "isbn": "123", "total_copies": 1})
    m_res = client.post("/members", json={"name": "Frank", "email": "frank@example.com"})
    book_id = b_res.get_json()["id"]
    member_id = m_res.get_json()["id"]

    loan_res = client.post("/loans", json={"book_id": book_id, "member_id": member_id})
    assert loan_res.status_code == 201
    loan_id = loan_res.get_json()["id"]

    updated_b = client.get(f"/books/{book_id}").get_json()
    assert updated_b["available_copies"] == 0

    return_res = client.put(f"/loans/{loan_id}/return")
    assert return_res.status_code == 200

    restored_b = client.get(f"/books/{book_id}").get_json()
    assert restored_b["available_copies"] == 1

def test_lookup_loans_by_params(client):
    """Test GET /loans?member_id= filter functionality (R11, R14, R23)."""
    b_res = client.post("/books", json={"title": "Domain-Driven Design", "author": "Eric Evans", "isbn": "456", "total_copies": 2})
    m_res = client.post("/members", json={"name": "Grace", "email": "grace@example.com"})
    book_id = b_res.get_json()["id"]
    member_id = m_res.get_json()["id"]

    client.post("/loans", json={"book_id": book_id, "member_id": member_id})

    response = client.get(f"/loans?member_id={member_id}")
    assert response.status_code == 200
    loans = response.get_json()
    assert len(loans) >= 1
    assert loans[0]["member_id"] == member_id