"""Server-side pagination: returns one page of rows and the full match count in `X-Total-Count`."""

from fastapi import Response

MAX_PAGE = 500


def paginate(query, response: Response, skip: int, limit: int, *order_by):
    total = query.order_by(None).count()
    response.headers["X-Total-Count"] = str(total)
    skip = max(skip, 0)
    limit = max(1, min(limit, MAX_PAGE))
    return query.order_by(*order_by).offset(skip).limit(limit).all()
