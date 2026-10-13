def model_to_dict(obj, **extra) -> dict:
    """
    Serialize an ORM row to its own column values plus any computed `extra` fields.

    Returning ORM objects directly makes FastAPI also serialize every loaded
    relationship, which leaks nested rows such as Users (with password hashes).
    """
    data = {column.key: getattr(obj, column.key) for column in obj.__table__.columns}
    data.update(extra)
    return data
