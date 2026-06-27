from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Table, BigInteger
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import models_users as mu
from sqlalchemy.exc import OperationalError
import migration

engine = create_engine('sqlite:///servers.db', connect_args={"check_same_thread": False})
Base = declarative_base()
Session = sessionmaker(bind=engine)
session = Session()

members = Table('members', Base.metadata,
                Column('server_id', Integer, ForeignKey('servers.id')),
                Column('user_id', Integer))


class Server(Base):
    __tablename__ = 'servers'
    id = Column(Integer, primary_key=True)
    public_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=False)
    owner_id = Column(Integer, nullable=False)
    private = Column(Boolean, default=False)
    code = Column(String, nullable=True)
    accent_color = Column(String, nullable=True)
    description = Column(String, nullable=True)
    channels = relationship('Channel', back_populates='server')


class Channel(Base):
    __tablename__ = 'channels'
    id = Column(Integer, primary_key=True)
    server_id = Column(Integer, ForeignKey('servers.id'))
    name = Column(String, nullable=False)
    private = Column(Boolean, default=False)
    allowed_roles = Column(String, nullable=True)  # comma-separated role ids
    allowed_users = Column(String, nullable=True)  # comma-separated user ids
    channel_type = Column(String, nullable=True)
    write_messages = Column(Boolean, default=True)
    server = relationship('Server', back_populates='channels')


class Role(Base):
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True)
    server_id = Column(Integer, ForeignKey('servers.id'), nullable=False)
    name = Column(String, nullable=False)
    administrator = Column(Boolean, default=False)
    write_messages = Column(Boolean, default=True)
    edit_server = Column(Boolean, default=False)
    create_threads = Column(Boolean, default=True)
    write_threads = Column(Boolean, default=True)
    edit_threads = Column(Boolean, default=True)
    create_channels = Column(Boolean, default=False)
    edit_channels = Column(Boolean, default=False)
    color = Column(String, nullable=True)
    group_members = Column(Boolean, default=False)


role_assignments = Table('role_assignments', Base.metadata,
                         Column('server_id', Integer, ForeignKey('servers.id')),
                         Column('user_id', Integer),
                         Column('role_id', Integer, ForeignKey('roles.id'))
                         )


class ServerMessage(Base):
    __tablename__ = 'server_messages'
    id = Column(Integer, primary_key=True)
    server_id = Column(Integer, ForeignKey('servers.id'), nullable=False)
    channel_id = Column(Integer, ForeignKey('channels.id'), nullable=False)
    sender_id = Column(Integer, nullable=False)
    content = Column(String, nullable=False)
    timestamp = Column(String, nullable=False)
    edited = Column(Boolean, default=False)
    deleted = Column(Boolean, default=False)


def init_db():
    Base.metadata.create_all(engine)


def create_server(name, owner_id, private=False, code=None):
    import random
    # generate unique public_id in range [1000, 9999999999]
    def gen():
        return random.randint(1000, 9999999999)
    pid = gen()
    while session.query(Server).filter_by(public_id=pid).first():
        pid = gen()
    s = Server(public_id=pid, name=name, owner_id=owner_id, private=private, code=code)
    session.add(s)
    session.commit()
    # create default channel
    create_channel(s.id, 'general')
    # create default @everyone role
    create_role(s.id, 'everyone', administrator=False, write_messages=True)
    return s


def create_role(server_id, name, administrator=False, write_messages=True, edit_server=False, create_threads=True, write_threads=True, edit_threads=True, create_channels=False, edit_channels=False):
    r = Role(server_id=server_id, name=name, administrator=administrator, write_messages=write_messages, edit_server=edit_server, create_threads=create_threads, write_threads=write_threads, edit_threads=edit_threads, create_channels=create_channels, edit_channels=edit_channels)
    session.add(r)
    session.commit()
    return r


def update_role(role_id, **kwargs):
    r = get_role_by_id(role_id)
    if not r:
        return None
    for k, v in kwargs.items():
        if hasattr(r, k):
            setattr(r, k, v)
    session.commit()
    return r


def get_role_members(server_id, role_id):
    conn = engine.connect()
    res = conn.execute(role_assignments.select().where((role_assignments.c.server_id == server_id) & (role_assignments.c.role_id == role_id))).fetchall()
    conn.close()
    return [r.user_id for r in res]


def get_roles(server_id):
    return session.query(Role).filter_by(server_id=server_id).all()


def get_role_by_id(role_id):
    return session.query(Role).get(role_id)


def assign_role(server_id, user_id, role_id):
    conn = engine.connect()
    conn.execute(role_assignments.insert().values(server_id=server_id, user_id=user_id, role_id=role_id))
    conn.close()


def get_user_role(server_id, user_id):
    conn = engine.connect()
    res = conn.execute(role_assignments.select().where((role_assignments.c.server_id == server_id) & (role_assignments.c.user_id == user_id))).fetchone()
    conn.close()
    if not res:
        return None
    return get_role_by_id(res.role_id)


def get_member_tuples(server_id):
    """Return list of (user_id, username) for members of a server."""
    conn = engine.connect()
    res = conn.execute(members.select().where(members.c.server_id == server_id)).fetchall()
    conn.close()
    user_ids = [r.user_id for r in res]
    users = []
    from models_users import get_user_by_id
    for uid in user_ids:
        u = get_user_by_id(uid)
        users.append((uid, u.username if u else str(uid)))
    return users


def has_permission(user_id, server_id, permission_name):
    # owner always has permissions
    s = get_server(server_id)
    if s and s.owner_id == user_id:
        return True
    role = get_user_role(server_id, user_id)
    if not role:
        # if no assigned role, default to everyone role
        everyone = session.query(Role).filter_by(server_id=server_id, name='everyone').first()
        role = everyone
    if not role:
        return False
    if getattr(role, 'administrator', False):
        return True
    return bool(getattr(role, permission_name, False))


def list_servers():
    try:
        return session.query(Server).all()
    except OperationalError as e:
        # likely missing column(s) in existing DB; attempt migration and retry
        try:
            migration.migrate_all()
        except Exception:
            raise
        return session.query(Server).all()


def get_server(server_id):
    return session.query(Server).get(server_id)


def get_server_by_public_id(public_id):
    return session.query(Server).filter_by(public_id=public_id).first()


def create_channel(server_id, name):
    c = Channel(server_id=server_id, name=name)
    session.add(c)
    session.commit()
    return c


def create_channel_with_access(server_id, name, private=False, allowed_roles=None, allowed_users=None):
    # allowed_roles and allowed_users can be lists of ints
    ar = None
    au = None
    if allowed_roles:
        ar = ','.join(str(int(x)) for x in allowed_roles)
    if allowed_users:
        au = ','.join(str(int(x)) for x in allowed_users)
    c = Channel(server_id=server_id, name=name, private=bool(private), allowed_roles=ar, allowed_users=au, channel_type='text', write_messages=True)
    session.add(c)
    session.commit()
    return c


def update_channel(channel_id, **kwargs):
    c = session.query(Channel).get(channel_id)
    if not c:
        return None
    for k, v in kwargs.items():
        if hasattr(c, k):
            setattr(c, k, v)
    session.commit()
    return c


def delete_channel(channel_id):
    # remove messages and channel record
    conn = engine.connect()
    try:
        conn.execute(ServerMessage.__table__.delete().where(ServerMessage.channel_id == channel_id))
        conn.execute(Channel.__table__.delete().where(Channel.id == channel_id))
    finally:
        conn.close()


def delete_server(server_id):
    conn = engine.connect()
    try:
        # delete server messages
        conn.execute(ServerMessage.__table__.delete().where(ServerMessage.server_id == server_id))
        # delete channels
        conn.execute(Channel.__table__.delete().where(Channel.server_id == server_id))
        # delete role assignments and roles
        conn.execute(role_assignments.delete().where(role_assignments.c.server_id == server_id))
        conn.execute(Role.__table__.delete().where(Role.server_id == server_id))
        # delete members entries
        conn.execute(members.delete().where(members.c.server_id == server_id))
        # delete server
        conn.execute(Server.__table__.delete().where(Server.id == server_id))
    finally:
        conn.close()


def channel_is_accessible(channel, user_id):
    # channel may be Channel object or id
    if isinstance(channel, int):
        channel = session.query(Channel).get(channel)
    if not channel:
        return False
    if not channel.private:
        return True
    # owner bypass not known here; caller should check server owner
    # check explicit user allow
    if channel.allowed_users:
        try:
            uids = [int(x) for x in channel.allowed_users.split(',') if x]
            if int(user_id) in uids:
                return True
        except Exception:
            pass
    # check roles
    if channel.allowed_roles:
        try:
            rids = [int(x) for x in channel.allowed_roles.split(',') if x]
            # get user's role
            role = get_user_role(channel.server_id, user_id)
            if role and role.id in rids:
                return True
        except Exception:
            pass
    return False


def get_channels(server_id):
    return session.query(Channel).filter_by(server_id=server_id).all()


def add_member(server_id, user_id):
    conn = engine.connect()
    conn.execute(members.insert().values(server_id=server_id, user_id=user_id))
    conn.close()


def get_members(server_id):
    conn = engine.connect()
    res = conn.execute(members.select().where(members.c.server_id == server_id)).fetchall()
    conn.close()
    user_ids = [r.user_id for r in res]
    users = []
    for uid in user_ids:
        u = mu.get_user_by_id(uid)
        users.append(u.username if u else f'User {uid}')
    return users


def get_servers_for_user(user_id):
    conn = engine.connect()
    res = conn.execute(members.select().where(members.c.user_id == user_id)).fetchall()
    conn.close()
    server_ids = [r.server_id for r in res]
    return session.query(Server).filter(Server.id.in_(server_ids)).all() if server_ids else []


def save_server_message(server_id, channel_id, sender_id, content, timestamp):
    ts = timestamp or ''
    m = ServerMessage(server_id=server_id, channel_id=channel_id, sender_id=sender_id, content=content, timestamp=ts)
    session.add(m)
    session.commit()
    return m


def get_message_by_id(message_id):
    return session.query(ServerMessage).get(message_id)


def edit_message(message_id, new_content):
    m = get_message_by_id(message_id)
    if not m:
        return None
    m.content = new_content
    m.edited = True
    session.commit()
    return m


def delete_message(message_id):
    m = get_message_by_id(message_id)
    if not m:
        return None
    m.deleted = True
    session.commit()
    return m


def get_channel_history(server_id, channel_id, limit=500):
    return session.query(ServerMessage).filter_by(server_id=server_id, channel_id=channel_id).order_by(ServerMessage.id).limit(limit).all()
