from sqlalchemy import create_engine, Column, Integer, String, Table, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from flask_login import UserMixin
from datetime import datetime

engine = create_engine('sqlite:///users.db', connect_args={"check_same_thread": False})
Base = declarative_base()
Session = sessionmaker(bind=engine)
session = Session()

friends = Table('friends', Base.metadata,
                Column('user_id', Integer, ForeignKey('users.id')),
                Column('friend_id', Integer, ForeignKey('users.id'))
                )


class User(Base, UserMixin):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    avatar = Column(String, nullable=True)
    friends = relationship('User', secondary=friends,
                           primaryjoin=id == friends.c.user_id,
                           secondaryjoin=id == friends.c.friend_id)


def init_db():
    Base.metadata.create_all(engine)


def create_user(username, password_hash):
    u = User(username=username, password_hash=password_hash)
    session.add(u)
    session.commit()
    return u


def get_user_by_username(username):
    return session.query(User).filter_by(username=username).first()


def get_user_by_id(uid):
    return session.query(User).get(uid)


def add_friend(user_id, friend_id):
    u = get_user_by_id(user_id)
    f = get_user_by_id(friend_id)
    if f not in u.friends:
        u.friends.append(f)
        session.commit()


def get_friends(user_id):
    u = get_user_by_id(user_id)
    return u.friends if u else []


# Direct messages between users stored in users.db
class DirectMessage(Base):
    __tablename__ = 'direct_messages'
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    recipient_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    content = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    edited = Column(Boolean, default=False)
    deleted = Column(Boolean, default=False)


def save_dm(sender_id, recipient_id, content, timestamp=None):
    ts = timestamp or datetime.utcnow()
    m = DirectMessage(sender_id=sender_id, recipient_id=recipient_id, content=content, timestamp=ts)
    session.add(m)
    session.commit()
    return m


def get_dm_history(user_a, user_b, limit=500):
    a = int(user_a)
    b = int(user_b)
    msgs = session.query(DirectMessage).filter(
        ((DirectMessage.sender_id == a) & (DirectMessage.recipient_id == b)) |
        ((DirectMessage.sender_id == b) & (DirectMessage.recipient_id == a))
    ).order_by(DirectMessage.timestamp).limit(limit).all()
    result = []
    for m in msgs:
        sender = get_user_by_id(m.sender_id)
        result.append({'id': m.id, 'sender_id': m.sender_id, 'sender': sender.username if sender else str(m.sender_id), 'content': m.content, 'ts': m.timestamp.isoformat(), 'edited': bool(m.edited), 'deleted': bool(m.deleted)})
    return result


def get_dm_by_id(mid):
    return session.query(DirectMessage).get(mid)


def edit_dm(mid, new_content):
    m = get_dm_by_id(mid)
    if not m:
        return None
    m.content = new_content
    m.edited = True
    session.commit()
    return m


def delete_dm(mid):
    m = get_dm_by_id(mid)
    if not m:
        return None
    m.deleted = True
    session.commit()
    return m
