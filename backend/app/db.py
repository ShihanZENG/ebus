from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .config import database_url


def build_engine(url=None):
    url = url or database_url()
    kwargs = {'pool_pre_ping': True}
    if url.startswith('sqlite'):
        kwargs['connect_args'] = {'check_same_thread': False}
    engine = create_engine(url, **kwargs)
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def enable_fk(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    return engine


def sessions(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


