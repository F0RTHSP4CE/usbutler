# USB Butler REST API

The USB Butler backend exposes a small REST API for managing card holders. All endpoints return JSON and live under the Flask server that powers the web UI (defaults to `http://localhost:8000`).

> **Tip:** When the server starts from `python -m app.web.server`, the API and UI share the same origin. You can use tools such as `curl`, Postman, or the built-in tests to interact with these endpoints.

## Common Conventions

- `Content-Type: application/json` is required for endpoints that accept a request body.
- Successful responses include `{ "success": true }`; errors return `{ "success": false, "error": "..." }` and an appropriate HTTP status code.
- Identifiers (`identifier` or `identifier_value`) can be a UID, PAN, or any other stable card/token value.

---

## Create (or attach) a card

```
POST /api/users
```

Create a new user with an initial card, or attach a card to an existing user by passing a `user_id`.

**Request Body**
```jsonc
{
  "identifier": "A1B2C3D4",          // required
  "identifier_type": "UID",          // optional, defaults to "UID"
  "name": "Jane Doe",                // required when creating a new user
  "access_level": "user",            // optional, defaults to "user" ("user" or "admin")
  "user_id": "...",                  // optional; set to attach to an existing user
  "metadata": {                       // optional extra information stored with the identifier
    "issuer": "Visa",
    "expiry": "2507"
  }
}
```

**Responses**
- `201 Created` with `{ "success": true, "user": { ... } }` for new users.
- `200 OK` with `{ "success": true, "user": { ... } }` when attaching a card.
- `400`, `404`, or `409` with `{ "success": false, "error": "..." }` when validation fails or the card already exists.

---

## Delete a user

```
DELETE /api/users/<user_id>
```

Removes the user and all associated identifiers.

**Responses**
- `200 OK` with `{ "success": true }` on success.
- `404 Not Found` if the user does not exist.

---

## Pause (deactivate) a user

```
POST /api/users/<user_id>/pause
```

Marks the user as inactive without deleting their identifiers. A paused user cannot unlock the door.

**Responses**
- `200 OK` with `{ "success": true, "user": { ... "active": false ... } }`.
- `404 Not Found` if the user does not exist.

---

## Resume (reactivate) a user

```
POST /api/users/<user_id>/resume
```

Reactivates a previously paused user.

**Responses**
- `200 OK` with `{ "success": true, "user": { ... "active": true ... } }`.
- `404 Not Found` if the user does not exist.

---

## Lookup a user by card number / UID

```
GET /api/users/by-identifier/<identifier_value>
```

Retrieves the user record that owns a specific identifier. The identifier in the URL should be URL-encoded if it contains special characters.

**Responses**
- `200 OK` with `{ "success": true, "user": { ... } }` when found.
- `404 Not Found` if no user owns the identifier.
- `400 Bad Request` if the identifier value is missing.

---

## Related Endpoints

Existing endpoints that remain available:

- `GET /api/users` – list all users.
- `DELETE /api/users/<user_id>/identifiers/<identifier_value>` – remove a specific card from a user.

Refer to the source in `app/web/server.py` or the unit tests in `tests/test_web.py` for additional examples.
