from mongoengine import connect, disconnect
from mongoengine.connection import ConnectionFailure, get_connection

from app.core.config import Settings, get_settings


def connect_to_mongo(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    try:
        get_connection(alias=settings.mongodb_alias)
        return
    except ConnectionFailure:
        pass

    if settings.mongo_mock:
        import mongomock

        connect(
            db=settings.mongodb_db,
            host="mongodb://localhost",
            alias=settings.mongodb_alias,
            mongo_client_class=mongomock.MongoClient,
            uuidRepresentation="standard",
        )
        return

    connect(
        db=settings.mongodb_db,
        host=settings.mongodb_uri,
        alias=settings.mongodb_alias,
        uuidRepresentation="standard",
    )


def disconnect_mongo(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    disconnect(alias=settings.mongodb_alias)


def ping_database(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    connection = get_connection(alias=settings.mongodb_alias)
    connection.admin.command("ping")
    return True
