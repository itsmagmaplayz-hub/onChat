from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_wtf import CSRFProtect
import os
from pathlib import Path
import uuid
import models_users as mu
import models_servers as ms

app = Flask(__name__)
# Stronger secret: prefer env var, else generate a random key at startup
app.config['SECRET_KEY'] = os.environ.get('ONCHAT_SECRET') or uuid.uuid4().hex
csrf = CSRFProtect()
csrf.init_app(app)

# ensure upload folder exists
UPLOAD_FOLDER = Path(app.root_path) / 'static' / 'uploads'
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)

login_manager = LoginManager()
login_manager.init_app(app)

socketio = SocketIO(app, cors_allowed_origins='*')


@login_manager.user_loader
def load_user(user_id):
    return mu.get_user_by_id(int(user_id))


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if mu.get_user_by_username(username):
            flash('Username already exists')
            return redirect(url_for('signup'))
        mu.create_user(username, generate_password_hash(password))
        flash('Account created — please log in')
        return redirect(url_for('login'))
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = mu.get_user_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    friends = mu.get_friends(current_user.id)
    servers = ms.list_servers()
    my_servers = ms.get_servers_for_user(current_user.id)
    return render_template('dashboard.html', friends=friends, servers=servers, my_servers=my_servers)


@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    friend_name = request.form['friend_username']
    friend = mu.get_user_by_username(friend_name)
    if not friend:
        flash('User not found')
    else:
        mu.add_friend(current_user.id, friend.id)
        flash('Friend added')
    return redirect(url_for('dashboard'))


@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        flash('No file')
        return redirect(url_for('dashboard'))
    f = request.files['avatar']
    if f.filename == '':
        flash('No selected file')
        return redirect(url_for('dashboard'))
    filename = secure_filename(f.filename)
    # make filename unique
    name = f"{current_user.id}_{uuid.uuid4().hex}_{filename}"
    path = Path(app.config['UPLOAD_FOLDER']) / name
    f.save(path)
    mu_user = mu.get_user_by_id(current_user.id)
    mu_user.avatar = name
    mu.session.commit()
    flash('Avatar uploaded')
    return redirect(url_for('dashboard'))


@app.route('/upload_avatar_ajax', methods=['POST'])
@login_required
def upload_avatar_ajax():
    data = request.get_json()
    b64 = data.get('data')
    if not b64:
        return {'ok': False}, 400
    import base64
    header, encoded = b64.split(',', 1) if ',' in b64 else (None, b64)
    raw = base64.b64decode(encoded)
    filename = f"{current_user.id}_{uuid.uuid4().hex}.png"
    path = Path(app.config['UPLOAD_FOLDER']) / filename
    with open(path, 'wb') as f:
        f.write(raw)
    mu_user = mu.get_user_by_id(current_user.id)
    mu_user.avatar = filename
    mu.session.commit()
    return {'ok': True, 'filename': filename}


@app.route('/create_server', methods=['POST'])
@login_required
def create_server():
    name = request.form['server_name']
    private = bool(request.form.get('private'))
    code = request.form.get('code') if private else None
    server = ms.create_server(name, owner_id=current_user.id, private=private, code=code)
    ms.add_member(server.id, current_user.id)
    flash('Server created')
    return redirect(url_for('server_view', public_id=server.public_id))


@app.route('/server/<int:public_id>/settings')
@login_required
def server_settings(public_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    # only owner or edit_server permission
    if not ((current_user.id == server.owner_id) or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=server.public_id))
    roles = ms.get_roles(server.id)
    # build member info with current role
    member_tuples = ms.get_member_tuples(server.id)
    members_info = []
    for uid, uname in member_tuples:
        r = ms.get_user_role(server.id, uid)
        members_info.append({'id': uid, 'username': uname, 'role': r.name if r else None})
    return render_template('server_settings.html', server=server, roles=roles, members_info=members_info)


@app.route('/server/<public_id>/delete', methods=['POST'])
@app.route('/server/<int:public_id>/delete', methods=['POST'])
@login_required
def server_delete(public_id):
    try:
        pid = int(public_id)
    except Exception:
        pid = public_id
    server = ms.get_server_by_public_id(pid) if isinstance(pid, int) else ms.get_server_by_public_id(pid)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    # only server owner can delete
    if current_user.id != server.owner_id:
        flash('Permission denied')
        return redirect(url_for('server_settings', public_id=server.public_id))
    name = request.form.get('confirm_name')
    if name != server.name:
        flash('Server name did not match')
        return redirect(url_for('server_settings', public_id=server.public_id))
    # perform deletion
    ms.delete_server(server.id)
    flash('Server deleted')
    return redirect(url_for('dashboard'))



@app.route('/server/<int:public_id>/settings/update', methods=['POST'])
@login_required
def server_update(public_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=server.public_id))
    server.name = request.form.get('name')
    server.accent_color = request.form.get('accent_color')
    server.description = request.form.get('description')
    ms.session.commit()
    flash('Server updated')
    return redirect(url_for('server_settings', public_id=public_id))


@app.route('/server/<int:public_id>/roles/create', methods=['POST'])
@login_required
def server_role_create(public_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=server.public_id))
    name = request.form.get('role_name')
    administrator = bool(request.form.get('administrator'))
    write_messages = bool(request.form.get('write_messages'))
    create_channels = bool(request.form.get('create_channels'))
    r = ms.create_role(server.id, name, administrator=administrator, write_messages=write_messages, create_channels=create_channels)
    flash(f'Created role {r.name}')
    return redirect(url_for('server_settings', public_id=public_id))


@app.route('/server/<int:public_id>/roles/<int:role_id>')
@login_required
def role_edit(public_id, role_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=public_id))
    role = ms.get_role_by_id(role_id)
    if not role or role.server_id != server.id:
        flash('Role not found')
        return redirect(url_for('server_settings', public_id=public_id))
    members = ms.get_member_tuples(server.id)
    role_members = ms.get_role_members(server.id, role_id)
    return render_template('role_edit.html', server=server, role=role, members=[{'id':u,'username':n} for u,n in members], role_members=role_members)


@app.route('/server/<int:public_id>/roles/<int:role_id>/update', methods=['POST'])
@login_required
def role_update(public_id, role_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=public_id))
    role = ms.get_role_by_id(role_id)
    if not role or role.server_id != server.id:
        flash('Role not found')
        return redirect(url_for('server_settings', public_id=public_id))
    data = request.form
    updates = {}
    if 'name' in data:
        updates['name'] = data.get('name')
    if 'color' in data:
        updates['color'] = data.get('color')
    if 'group_members' in data:
        updates['group_members'] = True
    else:
        updates['group_members'] = False
    # permissions
    updates['administrator'] = bool(data.get('administrator'))
    updates['write_messages'] = bool(data.get('write_messages'))
    updates['edit_server'] = bool(data.get('edit_server'))
    updates['create_threads'] = bool(data.get('create_threads'))
    updates['write_threads'] = bool(data.get('write_threads'))
    updates['edit_threads'] = bool(data.get('edit_threads'))
    updates['create_channels'] = bool(data.get('create_channels'))
    updates['edit_channels'] = bool(data.get('edit_channels'))
    ms.update_role(role_id, **updates)
    flash('Role updated')
    return redirect(url_for('role_edit', public_id=public_id, role_id=role_id))


@app.route('/server/<int:public_id>/roles/<int:role_id>/users/update', methods=['POST'])
@login_required
def role_update_users(public_id, role_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=public_id))
    role = ms.get_role_by_id(role_id)
    if not role or role.server_id != server.id:
        flash('Role not found')
        return redirect(url_for('server_settings', public_id=public_id))
    # iterate members and add/remove assignments based on checkboxes
    member_tuples = ms.get_member_tuples(server.id)
    conn = ms.engine.connect()
    # clear existing assignments for this role
    conn.execute(ms.role_assignments.delete().where((ms.role_assignments.c.server_id == server.id) & (ms.role_assignments.c.role_id == role_id)))
    for uid, uname in member_tuples:
        if request.form.get(f'user_{uid}'):
            conn.execute(ms.role_assignments.insert().values(server_id=server.id, user_id=uid, role_id=role_id))
    conn.close()
    flash('Role membership updated')
    return redirect(url_for('role_edit', public_id=public_id, role_id=role_id))


@app.route('/server/<int:public_id>/roles')
@login_required
def roles_overview(public_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=public_id))
    roles = ms.get_roles(server.id)
    role_counts = {r.id: len(ms.get_role_members(server.id, r.id)) for r in roles}
    return render_template('role_overview.html', server=server, roles=roles, role_counts=role_counts)


@app.route('/server/<int:public_id>/roles/assign', methods=['POST'])
@login_required
def server_role_assign(public_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=server.public_id))
    user_id = int(request.form.get('user_id'))
    role_id_raw = request.form.get('role_id')
    if not role_id_raw:
        # remove any existing assignment
        conn = ms.engine.connect()
        conn.execute(ms.role_assignments.delete().where((ms.role_assignments.c.server_id == server.id) & (ms.role_assignments.c.user_id == user_id)))
        conn.close()
        flash('Role removed')
        return redirect(url_for('server_settings', public_id=public_id))
    role_id = int(role_id_raw)
    # replace existing assignment if present
    conn = ms.engine.connect()
    conn.execute(ms.role_assignments.delete().where((ms.role_assignments.c.server_id == server.id) & (ms.role_assignments.c.user_id == user_id)))
    conn.execute(ms.role_assignments.insert().values(server_id=server.id, user_id=user_id, role_id=role_id))
    conn.close()
    flash('Role assigned')
    return redirect(url_for('server_settings', public_id=public_id))


@app.route('/server/<public_id>/channels/create', methods=['POST'])
@app.route('/server/<int:public_id>/channels/create', methods=['POST'])
@login_required
def server_channel_create(public_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'create_channels')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=public_id))
    name = request.form.get('channel_name')
    private = bool(request.form.get('private'))
    role_ids = request.form.getlist('role_id')
    user_ids = request.form.getlist('user_id')
    # convert to ints if present
    try:
        role_ids = [int(x) for x in role_ids]
    except Exception:
        role_ids = []
    try:
        user_ids = [int(x) for x in user_ids]
    except Exception:
        user_ids = []
    if private:
        ms.create_channel_with_access(server.id, name, private=True, allowed_roles=role_ids, allowed_users=user_ids)
    else:
        ms.create_channel_with_access(server.id, name, private=False)
    flash('Channel created')
    return redirect(url_for('server_view', public_id=public_id))


@app.route('/server/<public_id>/channels/<int:channel_id>/settings')
@app.route('/server/<int:public_id>/channels/<int:channel_id>/settings')
@login_required
def channel_settings(public_id, channel_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=public_id))
    channel = ms.session.query(ms.Channel).get(channel_id)
    if not channel or channel.server_id != server.id:
        flash('Channel not found')
        return redirect(url_for('server_settings', public_id=public_id))
    roles = ms.get_roles(server.id)
    members = [ {'id':u,'username':n} for u,n in ms.get_member_tuples(server.id) ]
    allowed_role_ids = [int(x) for x in (channel.allowed_roles or '').split(',') if x]
    allowed_user_ids = [int(x) for x in (channel.allowed_users or '').split(',') if x]
    return render_template('channel_settings.html', server=server, channel=channel, roles=roles, members=members, allowed_role_ids=allowed_role_ids, allowed_user_ids=allowed_user_ids)


@app.route('/server/<public_id>/channels/<int:channel_id>/settings/update', methods=['POST'])
@app.route('/server/<int:public_id>/channels/<int:channel_id>/settings/update', methods=['POST'])
@login_required
def channel_update(public_id, channel_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=public_id))
    channel = ms.session.query(ms.Channel).get(channel_id)
    if not channel or channel.server_id != server.id:
        flash('Channel not found')
        return redirect(url_for('server_settings', public_id=public_id))
    name = request.form.get('name')
    ctype = request.form.get('channel_type')
    write_messages = bool(request.form.get('write_messages'))
    private = bool(request.form.get('private'))
    role_ids = request.form.getlist('role_id')
    user_ids = request.form.getlist('user_id')
    try:
        role_ids = [int(x) for x in role_ids]
    except Exception:
        role_ids = []
    try:
        user_ids = [int(x) for x in user_ids]
    except Exception:
        user_ids = []
    updates = {'name': name, 'channel_type': ctype, 'write_messages': write_messages, 'private': private}
    updates['allowed_roles'] = ','.join(str(x) for x in role_ids) if role_ids else None
    updates['allowed_users'] = ','.join(str(x) for x in user_ids) if user_ids else None
    ms.update_channel(channel_id, **updates)
    flash('Channel updated')
    return redirect(url_for('channel_settings', public_id=public_id, channel_id=channel_id))


@app.route('/server/<public_id>/channels/<int:channel_id>/delete', methods=['POST'])
@app.route('/server/<int:public_id>/channels/<int:channel_id>/delete', methods=['POST'])
@login_required
def channel_delete(public_id, channel_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    if not (current_user.id == server.owner_id or ms.has_permission(current_user.id, server.id, 'edit_server')):
        flash('Permission denied')
        return redirect(url_for('server_view', public_id=public_id))
    channel = ms.session.query(ms.Channel).get(channel_id)
    if not channel or channel.server_id != server.id:
        flash('Channel not found')
        return redirect(url_for('server_settings', public_id=public_id))
    name = request.form.get('confirm_name')
    if name != channel.name:
        flash('Channel name did not match')
        return redirect(url_for('channel_settings', public_id=public_id, channel_id=channel_id))
    ms.delete_channel(channel_id)
    flash('Channel deleted')
    return redirect(url_for('server_settings', public_id=public_id))


@app.route('/join_server', methods=['POST'])
@login_required
def join_server():
    sid = int(request.form['server_id'])
    code = request.form.get('code')
    # treat submitted id as public_id
    server = ms.get_server_by_public_id(sid)
    if not server:
        flash('Server not found')
    elif server.private and server.code != code:
        flash('Invalid server code')
    else:
        ms.add_member(sid, current_user.id)
        flash('Joined server')
    return redirect(url_for('server_view', public_id=sid))


@app.route('/server/<int:public_id>')
@login_required
def server_view(public_id):
    server = ms.get_server_by_public_id(public_id)
    if not server:
        flash('Server not found')
        return redirect(url_for('dashboard'))
    channels = ms.get_channels(server.id)
    # filter channels by access
    visible_channels = []
    for c in channels:
        try:
            if not getattr(c, 'private', False):
                visible_channels.append(c)
            elif current_user.id == server.owner_id:
                visible_channels.append(c)
            elif ms.channel_is_accessible(c, current_user.id):
                visible_channels.append(c)
        except Exception:
            # fallback: include channel
            visible_channels.append(c)
    channels = visible_channels
    member_tuples = ms.get_member_tuples(server.id)
    # group members by role if role.group_members is enabled
    grouped = {}
    ungrouped = []
    for uid, uname in member_tuples:
        role = ms.get_user_role(server.id, uid)
        if role and getattr(role, 'group_members', False):
            grouped.setdefault(role.name, []).append({'id': uid, 'username': uname})
        else:
            ungrouped.append({'id': uid, 'username': uname})
    members = {'grouped': grouped, 'ungrouped': ungrouped}
    can_edit = (current_user.id == server.owner_id) or ms.has_permission(current_user.id, server.id, 'edit_server')
    roles = ms.get_roles(server.id)
    return render_template('server.html', server=server, channels=channels, members=members, can_edit_server=can_edit, roles=roles)


@app.route('/dm/<int:other_id>')
@login_required
def dm_view(other_id):
    other = mu.get_user_by_id(other_id)
    if not other:
        flash('User not found')
        return redirect(url_for('dashboard'))
    history = mu.get_dm_history(current_user.id, other_id)
    return render_template('dm.html', other=other, history=history)


@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')


@socketio.on('join')
def on_join(data):
    room = data['room']
    # enforce channel access for server channels
    try:
        parts = room.split('-')
        if parts[0] == 'server' and parts[2] == 'channel':
            sid = int(parts[1]); cid = int(parts[3])
            server = ms.get_server(sid)
            ch = ms.session.query(ms.Channel).get(cid)
            if ch and getattr(ch, 'private', False):
                allowed = False
                if server and current_user.id == server.owner_id:
                    allowed = True
                if ms.channel_is_accessible(ch, current_user.id):
                    allowed = True
                if not allowed:
                    emit('status', {'msg': 'Access denied to this channel.'}, room=request.sid)
                    return
    except Exception:
        pass
    join_room(room)
    emit('status', {'msg': f"{data['username']} has entered the room."}, room=room)
    # if joining a server channel, load recent history
    try:
        parts = room.split('-')
        if parts[0] == 'server' and parts[2] == 'channel':
            sid = int(parts[1]); cid = int(parts[3])
            msgs = ms.get_channel_history(sid, cid)
            history = []
            for m in msgs:
                sender = mu.get_user_by_id(m.sender_id)
                history.append({'id': m.id, 'username': sender.username if sender else str(m.sender_id), 'msg': m.content, 'ts': m.timestamp, 'edited': bool(m.edited), 'deleted': bool(m.deleted)})
            emit('history', {'room': room, 'messages': history}, room=request.sid)
    except Exception:
        pass


@socketio.on('dm')
def on_dm(data):
    room = data['room']
    # save DM into users.db
    try:
        sender = int(data.get('from'))
        recipient = int(data.get('to'))
        mu.save_dm(sender, recipient, data.get('msg'), None)
    except Exception:
        pass
    emit('dm', {'username': data['username'], 'msg': data['msg'], 'ts': data.get('ts')}, room=room)


@socketio.on('edit_dm')
def on_edit_dm(data):
    mid = int(data.get('message_id'))
    new = data.get('new_content')
    try:
        m = mu.get_dm_by_id(mid)
        if not m:
            return
        # allow edit if author
        if current_user.id == m.sender_id:
            mu.edit_dm(mid, new)
            emit('dm_edited', {'message_id': mid, 'new_content': new}, room=data.get('room'))
    except Exception:
        pass


@socketio.on('delete_dm')
def on_delete_dm(data):
    mid = int(data.get('message_id'))
    try:
        m = mu.get_dm_by_id(mid)
        if not m:
            return
        if current_user.id == m.sender_id:
            mu.delete_dm(mid)
            emit('dm_deleted', {'message_id': mid}, room=data.get('room'))
    except Exception:
        pass


@socketio.on('edit_message')
def on_edit_message(data):
    # data: {message_id, new_content}
    mid = int(data.get('message_id'))
    new = data.get('new_content')
    try:
        m = ms.get_message_by_id(mid)
        if not m:
            return
        # allow edit if author or server owner
        server = ms.get_server(m.server_id)
        if current_user.id == m.sender_id or (server and server.owner_id == current_user.id) or ms.has_permission(current_user.id, m.server_id, 'edit_threads'):
            ms.edit_message(mid, new)
            emit('message_edited', {'message_id': mid, 'new_content': new}, room=f'server-{m.server_id}-channel-{m.channel_id}')
    except Exception:
        pass


@socketio.on('delete_message')
def on_delete_message(data):
    mid = int(data.get('message_id'))
    try:
        m = ms.get_message_by_id(mid)
        if not m:
            return
        server = ms.get_server(m.server_id)
        if current_user.id == m.sender_id or (server and server.owner_id == current_user.id) or ms.has_permission(current_user.id, m.server_id, 'edit_threads'):
            ms.delete_message(mid)
            emit('message_deleted', {'message_id': mid}, room=f'server-{m.server_id}-channel-{m.channel_id}')
    except Exception:
        pass


@socketio.on('leave')
def on_leave(data):
    room = data['room']
    leave_room(room)
    emit('status', {'msg': f"{data['username']} has left the room."}, room=room)


@socketio.on('message')
def on_message(data):
    room = data['room']
    # messages for server channels are named like server-<sid>-channel-<cid>
    emit('message', {'username': data['username'], 'msg': data['msg'], 'ts': data.get('ts')} , room=room)
    try:
        parts = room.split('-')
        if parts[0] == 'server' and parts[2] == 'channel':
            sid = int(parts[1])
            cid = int(parts[3])
            ms.save_server_message(sid, cid, current_user.id, data['msg'], data.get('ts') or '')
    except Exception:
        pass


if __name__ == '__main__':
    mu.init_db()
    ms.init_db()
    # run simple migrations to add new columns if DBs existed
    try:
        import migration
        migration.migrate_all()
    except Exception:
        pass
    port = int(os.environ.get('PORT', '5000'))
    socketio.run(app, host='0.0.0.0', port=port)
