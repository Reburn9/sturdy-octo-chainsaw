from django import template

register = template.Library()


@register.filter
def state_name(value):
    return {
        "pending": "Awaiting review",
        "in_review": "In review",
        "agreed": "Agreed",
        "disputed": "Needs adjudication",
        "resolved": "Resolved",
    }.get(value, value)


@register.filter
def percent(value):
    return "—" if value is None else f"{value:g}%"


@register.filter
def bar_width(value, total):
    return round(100 * value / total) if total else 0
