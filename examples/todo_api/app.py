"""Tiny Todo API used as the example walked through the Swarm Suite pipeline.

It deliberately ships with several issues an honest review will catch:
SQL string concatenation, no input validation, no docstrings on public
endpoints, an N+1 access pattern, weak error handling. Don't deploy this.
"""

from __future__ import annotations

import sqlite3

from flask import Flask, jsonify, request

from .db import (
    add_todo,
    delete_todo,
    list_todos,
    list_todos_with_owner_name,  # N+1 inside
)

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/todos")
def todos_list():
    # No pagination, no auth -- both review-swarm findings.
    return jsonify(list_todos())


@app.get("/todos/with-owner")
def todos_with_owner():
    # Calls into list_todos_with_owner_name(), which hits the DB once
    # per row inside a loop -- the canonical N+1.
    return jsonify(list_todos_with_owner_name())


@app.post("/todos")
def todos_create():
    payload = request.get_json()
    title = payload["title"]              # KeyError on missing key -> 500
    owner = payload.get("owner", "anon")
    new_id = add_todo(title, owner)
    return jsonify({"id": new_id}), 201


@app.delete("/todos/<int:todo_id>")
def todos_delete(todo_id: int):
    try:
        delete_todo(todo_id)
    except sqlite3.Error:
        # Bare swallow -- review-swarm error-handling expert will flag it.
        pass
    return ("", 204)


if __name__ == "__main__":
    # Debug=True in production code is itself a finding. Left intentionally.
    app.run(debug=True)
