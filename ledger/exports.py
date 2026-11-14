import csv
import io
import json


def csv_cell(value):
    text = str(value)
    if text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def decision_rows(dataset):
    records = dataset.records.select_related("dataset").prefetch_related("reviews")
    for record in records.iterator(chunk_size=200):
        if record.decision is not None:
            yield {
                "id": record.external_id,
                "text": record.text,
                "label": record.decision,
                "state": record.state,
                "metadata": record.metadata,
                "review_count": len(record.reviews.all()),
                "version": record.version,
            }


def export_csv(dataset):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    fields = ["id", "text", "label", "state", "metadata", "review_count", "version"]
    writer.writerow(fields)
    yield buffer.getvalue()
    for row in decision_rows(dataset):
        buffer.seek(0)
        buffer.truncate(0)
        row["metadata"] = json.dumps(row["metadata"], ensure_ascii=False)
        writer.writerow(csv_cell(row[field]) for field in fields)
        yield buffer.getvalue()


def export_jsonl(dataset):
    for row in decision_rows(dataset):
        yield json.dumps(row, ensure_ascii=False) + "\n"
