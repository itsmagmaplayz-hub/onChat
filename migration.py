import sqlite3
from pathlib import Path

def add_column_if_missing(db_path, table, column_name, column_def):
    db = Path(db_path)
    if not db.exists():
        return
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if column_name not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_def}")
        conn.commit()
    conn.close()


def migrate_users_db():
    # add avatar to users
    add_column_if_missing('users.db', 'users', 'avatar', 'TEXT')
    # add edited/deleted to direct_messages
    add_column_if_missing('users.db', 'direct_messages', 'edited', 'INTEGER DEFAULT 0')
    add_column_if_missing('users.db', 'direct_messages', 'deleted', 'INTEGER DEFAULT 0')


def migrate_servers_db():
    # add edited/deleted to server_messages
    add_column_if_missing('servers.db', 'server_messages', 'edited', 'INTEGER DEFAULT 0')
    add_column_if_missing('servers.db', 'server_messages', 'deleted', 'INTEGER DEFAULT 0')
    # add server appearance columns
    add_column_if_missing('servers.db', 'servers', 'accent_color', 'TEXT')
    add_column_if_missing('servers.db', 'servers', 'description', 'TEXT')
    # create roles and role_assignments tables if missing
    conn = sqlite3.connect('servers.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY,
        server_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        administrator INTEGER DEFAULT 0,
        write_messages INTEGER DEFAULT 1,
        edit_server INTEGER DEFAULT 0,
        create_threads INTEGER DEFAULT 1,
        write_threads INTEGER DEFAULT 1,
        edit_threads INTEGER DEFAULT 1,
        create_channels INTEGER DEFAULT 0,
        edit_channels INTEGER DEFAULT 0,
        color TEXT,
        group_members INTEGER DEFAULT 0
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS role_assignments (
        server_id INTEGER,
        user_id INTEGER,
        role_id INTEGER
    )''')
    conn.commit(); conn.close()
    # add public_id to servers if missing and populate for existing rows
    add_column_if_missing('servers.db', 'servers', 'public_id', 'INTEGER')
    # add private/channel access columns to channels
    add_column_if_missing('servers.db', 'channels', 'private', 'INTEGER DEFAULT 0')
    add_column_if_missing('servers.db', 'channels', 'allowed_roles', 'TEXT')
    add_column_if_missing('servers.db', 'channels', 'allowed_users', 'TEXT')
    add_column_if_missing('servers.db', 'channels', 'channel_type', "TEXT DEFAULT 'text'")
    add_column_if_missing('servers.db', 'channels', 'write_messages', 'INTEGER DEFAULT 1')
    # populate missing public_id values
    conn = sqlite3.connect('servers.db')
    cur = conn.cursor()
    cur.execute("SELECT id, public_id FROM servers")
    rows = cur.fetchall()
    import random
    for rid, pid in rows:
        if pid is None:
            newpid = random.randint(1000, 9999999999)
            # ensure uniqueness
            cur.execute('SELECT COUNT(1) FROM servers WHERE public_id=?', (newpid,))
            while cur.fetchone()[0] > 0:
                newpid = random.randint(1000, 9999999999)
            cur.execute('UPDATE servers SET public_id=? WHERE id=?', (newpid, rid))
    conn.commit(); conn.close()
    # ensure roles have color and group_members columns
    add_column_if_missing('servers.db', 'roles', 'color', 'TEXT')
    add_column_if_missing('servers.db', 'roles', 'group_members', 'INTEGER DEFAULT 0')


def migrate_all():
    migrate_users_db()
    migrate_servers_db()
