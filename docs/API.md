# JSON API v1

The API uses the same Django session as the interface. Anonymous requests return 401; inaccessible datasets and records return 404. There are no hard-coded API credentials or bearer-token bypasses. Read requests do not require CSRF tokens. POST requests require the session cookie, `Content-Type: application/json`, and a matching `X-CSRFToken` header.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/datasets/` | Accessible datasets, 50 per page |
| GET | `/api/v1/datasets/{dataset_uuid}/` | Label schema and current metrics |
| GET | `/api/v1/datasets/{dataset_uuid}/records/` | Records, 50 per page; optional `state` filter |
| POST | `/api/v1/records/{record_uuid}/reviews/` | Create/revise the assigned user's vote |
| POST | `/api/v1/records/{record_uuid}/resolve/` | Manager adjudication of a complete disagreement |
| GET | `/health/` | Unauthenticated database/schema readiness, no dataset data |

List responses contain `count`, `page`, and `results`. Use `?page=2`; invalid page syntax returns 400 and out-of-range pages return 404. Record UUIDs identify API resources; `external_id` is the importer's string ID. Records are ordered by creation time and external ID.

## Submit a review

```json
{"label":"positive","comment":"The text explicitly recommends the feature.","version":1}
```

`label` must belong to the dataset. `comment` is optional for a review and required for adjudication, with a 2,000-character maximum. `version` must match the positive integer from the record response. Unknown fields are rejected. JSON request bodies are limited to 10,000 bytes.

A successful mutation returns the updated record, including its new version, state, current decision, and visible votes. Two writes using the same version cannot both succeed. Reload the record after a 409 before making another judgment; do not blindly retry the old payload.

## Calling from the browser console

After signing in and opening a record page, use its UUID and current version:

```javascript
const token = document.cookie.split('; ').find(c => c.startsWith('csrftoken='))?.split('=')[1];
const response = await fetch('/api/v1/records/REPLACE_WITH_RECORD_UUID/reviews/', {
  method: 'POST',
  headers: {'Content-Type': 'application/json', 'X-CSRFToken': token},
  body: JSON.stringify({label: 'positive', comment: 'Evidence in the text.', version: 1})
});
console.log(response.status, await response.json());
```

The request must still pass membership, reviewer role, assignment, allowed-label, resolution, and version checks. Before a reviewer has voted, other vote values and the decision are withheld in record JSON. Managers and viewers can inspect votes; reviewers cannot export other people's labels through the export endpoint.

## Errors

Workflow errors return `{"error":"message"}` with 400 (invalid input), 403 (forbidden), 404 (inaccessible resource), 409 (stale or locked record), 413 (body too large), or 415 (wrong content type). Invalid methods return 405 with an `Allow` header. Django's earlier CSRF and request-size middleware may instead return an HTML 403 or 400 response, so clients should check the response content type before decoding JSON.

Imports and user/membership management currently use HTML forms and CLI commands, not API endpoints. CSV/JSONL downloads use `/datasets/{dataset_uuid}/export/?format=csv` or `jsonl`. They include current agreed/adjudicated records only; CSV prefixes potentially executable spreadsheet cells with an apostrophe, while JSONL preserves the text exactly.
